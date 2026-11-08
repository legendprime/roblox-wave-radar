"""Insights on top of the waves: mechanics, stand-ins for private stats, winners vs flops,
opportunity scores, momentum, chart entries, your games, and the radar's own track record."""
import datetime as dt
import json
import math
import re
import statistics

from . import enrich
from .config import watchlist
from .db import iso, parse_iso

# Detected from titles + descriptions with simple keyword rules, so treat as rough.
MECHANICS = {
    "training / treadmill": r"treadmill|\btrain(ing|s)?\b|pull-?ups?|\bgym\b|lift(ing)? weights|\banvils?\b",
    "+1 per second": r"\+1\b|every second|per second|every click|per click",
    "stealing": r"\bsteal",
    "eggs / hatching": r"\beggs?\b|\bhatch",
    "pets / animals": r"\bpets?\b|\banimals?\b|\bcreatures?\b|\bducks?\b|\bdinos?\b",
    "brainrot": r"brainrot",
    "money base / tycoon": r"earn (money|cash|coins)|passive income|your base|\bbase\b|tycoon|generate (money|cash)|\bcash\b",
    "offline earnings": r"offline",
    "rebirth": r"\brebirths?\b|\bprestige|\bascend",
    "mutations / sizes": r"mutation|\bsizes?\b|\bshin(y|ies)\b|\bgiant\b",
    "rarity / luck": r"\brare\b|rarer|rarity|\bsecret\b|legendary|mythic|\brng\b|\bluck",
    "index / collect all": r"\bindex\b|collect (them )?all|\bcollection\b",
    "hazard escape": r"tsunami|\blava\b|\bflood|run (back|home|away)|chas(e|es|ing) you|catches you|escape (the|from)",
    "throw / kick / launch": r"\bthrow|\bkick|\blaunch|\bfling|\bshoot",
    "dig / mine / break": r"\bdig\b|\bmine\b|mining|pickaxe|\bbreak\b|\bcut\b|\bchop|\bcrack",
    "grow / farm": r"\bgrow\b|\bplant|\bseeds?\b|harvest|\bfarm|garden",
    "merge": r"\bmerge",
    "trading": r"\btrad(e|ing)\b",
    "fighting / bosses": r"\bpvp\b|\bfight|\bbattle|\bbosse?s?\b|\bpunch",
    "obby / climbing": r"\bobby|\bclimb|parkour|\btower\b",
    "ragdoll physics": r"ragdoll|\bphysics\b",
    "evolution / transform": r"evolv|evolution|transform",
    "horror / anomaly": r"horror|scary|anomal|creepy|it knows|poolrooms|backrooms",
    "with friends / co-op": r"with (your )?friends|team up|co-?op|\bsquad|2 player|multiplayer",
    "roleplay / life": r"roleplay|\brp\b|\blife\b|\bfamily\b|\bbaby\b",
    "vehicles": r"\bcars?\b|\bdriv(e|ing)\b|\bbikes?\b|scooter|\btrucks?\b|vehicle|tesla",
    "shop / business": r"\bshop\b|\bstore\b|business|customers?|\bsell\b",
    "events / admin abuse": r"admin abuse|\bevents?\b|limited time|\bconcert\b",
}
_MECH = {k: re.compile(v) for k, v in MECHANICS.items()}


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


class Insights:
    def __init__(self, radar, conn, cfg):
        self.R, self.conn, self.cfg, self.t = radar, conn, cfg, radar.t
        self.big = cfg["enrich"]["big_creator_members"]
        rows = conn.execute("SELECT universe_id, description, updated_at, creator_type, creator_id, "
                            "last_visits, last_favorites FROM games").fetchall()
        self.extra = {r["universe_id"]: r for r in rows}
        self._mech, self._prox = {}, {}
        latest = conn.execute("SELECT id FROM runs WHERE status IN ('ok','partial') ORDER BY id DESC LIMIT 1").fetchone()
        self.latest_run = latest["id"] if latest else None
        first = conn.execute("SELECT MIN(started_at) FROM runs WHERE status IN ('ok','partial')").fetchone()[0]
        self.tracking_start = first

    # ---- per game ------------------------------------------------------------------

    def mechanics(self, uid):
        if uid not in self._mech:
            g = self.R.games.get(uid)
            x = self.extra.get(uid)
            text = f"{g['name'] if g else ''} {x['description'] if x and x['description'] else ''}".lower()
            self._mech[uid] = [k for k, rx in _MECH.items() if rx.search(text)]
        return self._mech[uid]

    def proxies(self, uid):
        """Public stand-ins for stats Roblox keeps private."""
        if uid in self._prox:
            return self._prox[uid]
        c, t = self.conn, self.t
        out = {}
        last = c.execute("SELECT ts, visits, up_votes, down_votes FROM snapshots WHERE universe_id = ? AND visits IS NOT NULL "
                         "ORDER BY ts DESC LIMIT 1", (uid,)).fetchone()
        if last:
            lt = parse_iso(last["ts"])
            prev = c.execute("SELECT ts, visits FROM snapshots WHERE universe_id = ? AND visits IS NOT NULL AND ts <= ? AND ts >= ? "
                             "ORDER BY ts DESC LIMIT 1",
                             (uid, iso(lt - dt.timedelta(hours=18)), iso(lt - dt.timedelta(hours=40)))).fetchone()
            if prev and last["visits"] and prev["visits"] is not None:
                span = (lt - parse_iso(prev["ts"])).total_seconds() / 86400
                vpd = (last["visits"] - prev["visits"]) / span if span > 0 else None
                if vpd and vpd > 0:
                    out["visits_per_day"] = round(vpd)
                    avg = c.execute("SELECT AVG(playing) FROM snapshots WHERE universe_id = ? AND ts >= ? AND ts <= ?",
                                    (uid, prev["ts"], last["ts"])).fetchone()[0]
                    if avg:
                        out["minutes_per_visit"] = round(avg * 1440 / vpd, 1)
        votes = c.execute("SELECT up_votes, down_votes FROM snapshots WHERE universe_id = ? AND up_votes IS NOT NULL "
                          "ORDER BY ts DESC LIMIT 1", (uid,)).fetchone()
        if votes and (votes["up_votes"] or 0) + (votes["down_votes"] or 0) >= 20:
            out["like"] = round(100 * votes["up_votes"] / (votes["up_votes"] + votes["down_votes"]))
        x = self.extra.get(uid)
        if x and x["last_visits"] and x["last_favorites"] is not None and x["last_visits"] >= 1000:
            out["favs_per_1k"] = round(1000 * x["last_favorites"] / x["last_visits"], 1)
        if x and x["updated_at"]:
            out["last_update_days"] = round((t - parse_iso(x["updated_at"])).total_seconds() / 86400, 1)
        out["updates_14d"] = c.execute("SELECT COUNT(*) FROM updates WHERE universe_id = ? AND updated_at >= ?",
                                       (uid, iso(t - dt.timedelta(days=14)))).fetchone()[0]
        visits = x["last_visits"] if x else None
        b = enrich.badge_summary(c, uid, visits, t)
        if b:
            out["badges"] = b
        if x:
            ci = enrich.creator_info(c, x["creator_type"], x["creator_id"], self.big)
            if ci:
                out["creator"] = ci
        self._prox[uid] = out
        return out

    # ---- per wave --------------------------------------------------------------------

    def wave_mechanics(self, w, top=6):
        counts = {}
        for u in w["members"]:
            for m in self.mechanics(u):
                counts[m] = counts.get(m, 0) + 1
        n = max(1, len(w["members"]))
        return [{"name": m, "share": round(k / n, 2)} for m, k in
                sorted(counts.items(), key=lambda kv: -kv[1]) if k / n >= 0.25][:top]

    def winners_vs_flops(self, w):
        R = self.R
        eligible = [u for u in w["members"] if (R.age(u) or 0) >= 3]
        win = [u for u in eligible if (R.games[u]["peak_playing"] or 0) >= 1000]
        flop = [u for u in eligible if u not in win]
        if len(win) < 2 or len(flop) < 2:
            return None

        def share(group, test):
            return sum(1 for u in group if test(u)) / len(group)
        def updated_7d(u):
            """Updated in the last week AND at least a day after launch (a fresh launch isn't an update)."""
            last = self.proxies(u).get("last_update_days")
            age = R.age(u)
            return last is not None and age is not None and last <= 7 and age - last >= 1
        out = {"winners": len(win), "flops": len(flop),
               "like_w": _med(self.proxies(u).get("like") for u in win),
               "like_f": _med(self.proxies(u).get("like") for u in flop),
               "updated_w": round(share(win, updated_7d), 2), "updated_f": round(share(flop, updated_7d), 2),
               "more_in_winners": [], "more_in_flops": []}
        for m in MECHANICS:
            sw = share(win, lambda u: m in self.mechanics(u))
            sf = share(flop, lambda u: m in self.mechanics(u))
            if sw - sf >= 0.25 and sw * len(win) >= 2:
                out["more_in_winners"].append(m)
            elif sf - sw >= 0.25 and sf * len(flop) >= 2:
                out["more_in_flops"].append(m)
        out["more_in_winners"] = out["more_in_winners"][:4]
        out["more_in_flops"] = out["more_in_flops"][:3]
        return out

    def big_share(self, uids):
        total = big = 0
        for u in uids:
            p = self.R.playing(u)
            total += p
            ci = self.proxies(u).get("creator")
            if ci and ci["big"]:
                big += p
        return (big / total) if total else None

    # ---- opportunities -----------------------------------------------------------------

    def wave_score(self, w):
        hr, rr = w["hit_rate"], w.get("recent_hit_rate")
        succ = 0.3 if hr is None else (hr if rr is None else 0.5 * hr + 0.5 * rr)
        fresh = max(0.15, 1 - (w["leader_age"] or 90) / 90)
        mom = min(1.5, max(0.6, w["growth_72h"])) if w["growth_72h"] else 1.0
        bs = self.big_share(set(w["members"]) | {w["leader"]})
        comp = 1 - 0.5 * (bs or 0)
        lin = 1.15 if w["lineage"] else 1.0
        crowd = 1 / (1 + w["n7"] / 15)
        reasons = []
        if w.get("recent"):
            reasons.append(f"{w['recent_hits']} of {w['recent']} newest copies reached 1K")
        elif w["eligible"]:
            reasons.append(f"{w['hits']} of {w['eligible']} copies reached 1K")
        reasons.append(f"leader {w['leader_age']:.0f} days old" if w["leader_age"] is not None else "new leader")
        if w["growth_72h"]:
            reasons.append(f"players {'+' if w['growth_72h'] >= 1 else ''}{(w['growth_72h'] - 1) * 100:.0f}% in 3 days")
        if bs is not None:
            reasons.append("mostly small developers" if bs < 0.3 else f"big studios hold {bs * 100:.0f}% of players")
        if w["lineage"]:
            reasons.append("tycoon lineage")
        return 100 * succ * fresh * mom * comp * lin * crowd, reasons

    def lone_score(self, x):
        g24 = x["growth_24h"]
        fresh = max(0.1, 1 - x["age"] / 40)
        size = min(1.0, math.log10(max(10, x["playing"])) / 5)
        mom = min(2.0, max(0.5, g24)) / 2 if g24 else 0.5
        forming = 1.25 if x["n_copies"] >= 2 else 1.0
        g = self.R.games[x["uid"]]
        lin = 1.15 if g["genre_l2"] in set(self.cfg["radar"]["lineage_subgenres"]) else 1.0
        reasons = [f"{x['playing']:,} playing at {x['age']:.0f} days old"]
        if g24:
            reasons.append(f"{'+' if g24 >= 1 else ''}{(g24 - 1) * 100:.0f}% in 24h")
        reasons.append(f"{x['n_copies']} lookalikes so far" if x["n_copies"] else "no copies yet")
        if lin > 1:
            reasons.append("tycoon lineage")
        return 60 * fresh * size * mom * forming * lin, reasons

    def opportunities(self, limit=6):
        out = []
        for w in self.R.waves:
            if w["stage"] in ("jump", "starting"):
                s, why = self.wave_score(w)
                out.append({"kind": "wave", "key": w["key"], "label": w["label"], "stage": w["stage"],
                            "score": s, "why": why, "leader": w["leader"]})
        for x in self.R.lone[:15]:
            s, why = self.lone_score(x)
            out.append({"kind": "lone", "key": str(x["uid"]), "label": self.R.games[x["uid"]]["name"],
                        "stage": "lone", "score": s, "why": why, "leader": x["uid"]})
        out.sort(key=lambda o: o["score"], reverse=True)
        top = out[:limit]
        best = top[0]["score"] if top else 1
        for o in top:
            o["score"] = round(100 * o["score"] / best) if best else 0
        return top

    # ---- lists ---------------------------------------------------------------------------

    def wave_of(self):
        m = {}
        for w in self.R.waves:
            for u in w["members"]:
                m.setdefault(u, w)
            m.setdefault(w["leader"], w)
        return m

    def rising(self, limit=25):
        R, wave_of = self.R, self.wave_of()
        rows = []
        for uid, g in R.games.items():
            age = R.age(uid)
            if age is None or age > 45 or R.playing(uid) < 1000:
                continue
            g24 = R.growth([uid], 24)
            if g24 is None or g24 <= 1.05:
                continue
            w = wave_of.get(uid)
            rows.append({"uid": uid, "growth_24h": g24, "wave": w["label"] if w else None,
                         "wave_stage": w["stage"] if w else None})
        rows.sort(key=lambda r: r["growth_24h"], reverse=True)
        return rows[:limit]

    def chart_entries(self, limit=30):
        since = iso(self.t - dt.timedelta(hours=24))
        pos = {}
        if self.latest_run:
            for r in self.conn.execute("SELECT universe_id, sort_id, MIN(position) FROM sort_hits WHERE run_id = ? "
                                       "GROUP BY universe_id, sort_id", (self.latest_run,)):
                pos[(r[0], r[1])] = r[2]
        rows = self.conn.execute("SELECT universe_id, detail, ts FROM events WHERE kind = 'entered_sort' AND baseline = 0 "
                                 "AND ts >= ? ORDER BY ts DESC", (since,)).fetchall()
        out = [{"uid": r["universe_id"], "chart": r["detail"], "position": pos.get((r["universe_id"], r["detail"])),
                "ts": r["ts"]} for r in rows if r["universe_id"] in self.R.games]
        order = {"up-and-coming": 0, "top-trending": 1, "trending-in-simulation": 2, "top-playing-now": 3}
        out.sort(key=lambda x: (order.get(x["chart"], 9), x["position"] or 999))
        return out[:limit]

    def my_games(self):
        wave_of = self.wave_of()
        out = []
        for uid, w in watchlist(self.conn, self.cfg).items():
            if w["kind"] != "mine":
                continue
            wv = wave_of.get(uid)
            out.append({"uid": uid, "note": w["note"], "wave": wv["label"] if wv else None,
                        "wave_stage": wv["stage"] if wv else None})
        out.sort(key=lambda x: self.R.playing(x["uid"]), reverse=True)
        return out

    def mechanic_trends(self, min_games=5):
        R = self.R
        young = [u for u in R.games if (R.age(u) or 99) <= self.cfg["radar"]["wave_window_days"]]
        rows = []
        for m in MECHANICS:
            games = [u for u in young if m in self.mechanics(u)]
            eligible = [u for u in games if (R.age(u) or 0) >= 3]
            if len(eligible) < min_games:
                continue
            hits = [u for u in eligible if (R.games[u]["peak_playing"] or 0) >= 1000]
            this_week = sum(1 for u in games if (R.age(u) or 99) <= 7)
            last_week = sum(1 for u in games if 7 < (R.age(u) or 99) <= 14)
            rows.append({"name": m, "games": len(games), "eligible": len(eligible), "hits": len(hits),
                         "hit_rate": round(len(hits) / len(eligible), 3),
                         "new_this_week": this_week, "new_last_week": last_week,
                         "top": sorted(games, key=R.playing, reverse=True)[:3]})
        rows.sort(key=lambda r: (r["hit_rate"], r["hits"]), reverse=True)
        return rows

    # ---- the radar's own track record -------------------------------------------------

    def record_track(self):
        """Store today's stage for every wave, and the stage each new copy's wave had on its creation day."""
        day = iso(self.t)[:10]
        c = self.conn
        for w in self.R.waves:
            c.execute("INSERT OR REPLACE INTO wave_days VALUES (?,?,?,?,?,?,?,?)",
                      (day, w["key"], w["label"], w["stage"], w["n"], w["hits"], w["eligible"], w["total"]))
        if not self.tracking_start:
            c.commit()
            return
        done = {r[0] for r in c.execute("SELECT universe_id FROM copy_stage")}
        for w in self.R.waves:
            for u in w["members"]:
                created = self.R.games[u]["created_at"]
                if u in done or u == w["leader"] or not created or created < self.tracking_start:
                    continue
                row = c.execute("SELECT stage FROM wave_days WHERE wave = ? AND day <= ? ORDER BY day DESC LIMIT 1",
                                (w["key"], created[:10])).fetchone()
                c.execute("INSERT OR IGNORE INTO copy_stage VALUES (?,?,?,?,?)",
                          (u, w["key"], row["stage"] if row else "before the wave was spotted", created, iso(self.t)))
                done.add(u)
        c.commit()

    def track_record(self, window_days=14):
        c, t = self.conn, self.t
        rows = c.execute("SELECT * FROM copy_stage").fetchall()
        by = {}
        for r in rows:
            created = parse_iso(r["created_at"])
            end = created + dt.timedelta(days=window_days)
            peak = c.execute("SELECT MAX(peak_playing) FROM daily WHERE universe_id = ? AND day >= ? AND day <= ?",
                             (r["universe_id"], r["created_at"][:10], iso(min(end, t))[:10])).fetchone()[0] or 0
            s = by.setdefault(r["stage"], {"stage": r["stage"], "launched": 0, "finished": 0, "hit1k": 0, "hit10k": 0,
                                           "running": 0, "running_hit1k": 0})
            s["launched"] += 1
            if end <= t:
                s["finished"] += 1
                s["hit1k"] += peak >= 1000
                s["hit10k"] += peak >= 10000
            else:
                s["running"] += 1
                s["running_hit1k"] += peak >= 1000
        start = self.tracking_start
        return {"since": start, "window_days": window_days,
                "first_results": iso(parse_iso(start) + dt.timedelta(days=window_days)) if start else None,
                "stages": sorted(by.values(), key=lambda s: ["jump", "starting", "watching", "crowded", "fading"].index(s["stage"])
                                 if s["stage"] in ("jump", "starting", "watching", "crowded", "fading") else 9)}

    def timelines(self, days=21):
        since = (self.t - dt.timedelta(days=days)).strftime("%Y-%m-%d")
        out = {}
        for r in self.conn.execute("SELECT day, wave, label, stage FROM wave_days WHERE day >= ? ORDER BY day", (since,)):
            w = out.setdefault(r["wave"], {"wave": r["wave"], "label": r["label"], "days": []})
            w["label"] = r["label"]
            w["days"].append({"day": r["day"], "stage": r["stage"]})
        keep = []
        for w in out.values():
            stages = [d["stage"] for d in w["days"]]
            if any(s in ("jump", "starting", "fading") for s in stages):
                w["jump_days"] = stages.count("jump")
                w["first_day"] = w["days"][0]["day"]
                keep.append(w)
        keep.sort(key=lambda w: (-w["jump_days"], w["label"]))
        return keep

    # ---- bookkeeping ------------------------------------------------------------------------

    def key_games(self, rising, limit):
        R = self.R
        order = []

        def add(u):
            if u not in order:
                order.append(u)
        for uid, w in watchlist(self.conn, self.cfg).items():
            add(uid)
        for w in R.waves:
            if w["stage"] in ("jump", "starting", "fading"):
                for u in [w["leader"], *w["best"], *w["newest"]]:
                    add(u)
        for x in R.lone:
            add(x["uid"])
            for u in x["copies"]:
                add(u)
        for r in rising:
            add(r["uid"])
        for w in R.waves:
            if w["stage"] == "crowded":
                add(w["leader"])
        young = sorted((u for u in R.games if (R.age(u) or 99) <= 45), key=R.playing, reverse=True)
        for u in young[:40]:
            add(u)
        return [u for u in order if u in R.games][:limit]

    def forming(self, warmed_up):
        """Lone breakouts that just got their first 2+ lookalikes: a wave may be forming."""
        row = self.conn.execute("SELECT value FROM meta WHERE key = 'lone_lookalikes'").fetchone()
        before = json.loads(row[0]) if row and row[0] else None
        now_map = {str(x["uid"]): x["n_copies"] for x in self.R.lone}
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('lone_lookalikes', ?)", (json.dumps(now_map),))
        self.conn.commit()
        if before is None or not warmed_up:
            return []
        out = []
        for x in self.R.lone:
            if before.get(str(x["uid"]), 0) < 2 <= x["n_copies"]:
                key = f"forming:{x['uid']}"
                if not self.conn.execute("SELECT 1 FROM alerts_log WHERE key = ?", (key,)).fetchone():
                    out.append({"kind": "forming", "key": key, "lone": x})
        return out
