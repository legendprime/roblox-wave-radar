"""Wave detection.

A wave is a group of recently created games whose titles share an idea
("ragdoll", "steal", "for animals", "dont splash"). For each wave we measure
how fast copies are appearing, whether the copies are succeeding, whether total
players are growing, and how old the leading game is, then give it a stage:

  starting  - a young breakout with only a few copies so far
  jump      - copies with a twist are succeeding and it isn't crowded yet: the window
  crowded   - too many copies, copies mostly failing, or the leader is old
  fading    - total players falling
  watching  - none of the above yet

Every threshold lives in config.toml [radar], so the rules can be tuned.
"""
import collections
import datetime as dt
import re

from .db import iso, now, parse_iso

STOP = set("""
a an the to for and of in on at by with from my your our his her its it is be are was you me we i
or not no yes so if as up do get got go x2 x3 x4 x5 x10 x20 x50 x100 x1000 2x 3x 5x 10x 100x
upd update updates new event events beta alpha testing test release released soon early access
free op best ultimate super mega real part chapter season version v2 v3 v4 edition mode modes
plus pro max mini official classic remastered remake dont don cant wont lets how what who why
when where this that all one two can will make together
""".split())
GENERIC = set("""
simulator sim tycoon obby game games roblox rp roleplay experience place hub lobby server servers
private public world worlds battle clone copy
""".split())

BRACKETS = re.compile(r"[\[\(\{【「].*?[\]\)\}】」]")
WORD = re.compile(r"\+1|[a-z0-9]+")
SPARK = "▁▂▃▄▅▆▇█"
STAGES = ["jump", "starting", "watching", "crowded", "fading"]


# ---- title terms --------------------------------------------------------------------

def tokens(name):
    s = BRACKETS.sub(" ", (name or "").lower()).replace("’", "").replace("'", "")
    return WORD.findall(s)


def stem(w):
    if w == "+1" or len(w) <= 3:
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def _content(w, generic):
    return (w == "+1" or (len(w) >= 3 and not w.isdigit())) and w not in STOP and w not in generic


def terms_of(name, generic=GENERIC, surface=None):
    """Words and word pairs from a title that can define a wave, e.g.
    'Throw Food For Animals' -> {throw, food, animal, throw food, food animal?, for animal}."""
    raw = tokens(name)
    st = [stem(t) for t in raw]
    if surface is not None:
        for r, s in zip(raw, st):
            surface[s][r] += 1
    out = set()
    for i, w in enumerate(st):
        nxt = st[i + 1] if i + 1 < len(st) else None
        if _content(w, generic):
            out.add(w)
            if nxt and _content(nxt, generic):
                out.add(f"{w} {nxt}")
        elif w == "for" and nxt and _content(nxt, generic):
            out.add(f"for {nxt}")
    return out


def display(term, surface):
    return " ".join(surface[p].most_common(1)[0][0] if surface.get(p) else p for p in term.split(" "))


# ---- helpers -------------------------------------------------------------------------

def _age_days(created, t):
    c = parse_iso(created)
    return None if c is None else (t - c).total_seconds() / 86400


def _run_near(conn, target, tolerance_h=4):
    row = conn.execute(
        """SELECT id, started_at FROM runs WHERE status IN ('ok','partial')
           ORDER BY ABS(julianday(started_at) - julianday(?)) LIMIT 1""", (iso(target),)).fetchone()
    if not row:
        return None
    if abs((parse_iso(row["started_at"]) - target).total_seconds()) > tolerance_h * 3600:
        return None
    return row["id"]


def _snapshot(conn, run_id):
    if run_id is None:
        return {}
    return {r[0]: r[1] for r in conn.execute(
        "SELECT universe_id, playing FROM snapshots WHERE run_id = ?", (run_id,))}


def _growth(now_map, then_map, uids):
    both = [u for u in uids if u in now_map and u in then_map]
    if not both:
        return None
    before = sum(then_map[u] or 0 for u in both)
    after = sum(now_map[u] or 0 for u in both)
    return None if before <= 0 else after / before


def sparkline(values):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return SPARK[3] * len(vals)
    return "".join(SPARK[int((v - lo) / (hi - lo) * (len(SPARK) - 1))] for v in vals)


# ---- the analysis ----------------------------------------------------------------------

class Radar:
    def __init__(self, conn, cfg, t=None):
        self.conn, self.cfg, self.r = conn, cfg, cfg["radar"]
        self.t = t or now()
        self.generic = GENERIC | set(self.r["generic_words"])
        self.games = {g["universe_id"]: g for g in conn.execute(
            """SELECT universe_id, name, created_at, last_playing, peak_playing, genre_l1, genre_l2,
                      root_place_id, icon_url FROM games WHERE name IS NOT NULL""")}
        latest = conn.execute("SELECT id FROM runs WHERE status IN ('ok','partial') ORDER BY id DESC LIMIT 1").fetchone()
        self.now_map = _snapshot(conn, latest["id"]) if latest else {}
        for uid, g in self.games.items():
            self.now_map.setdefault(uid, g["last_playing"] or 0)
        self.then = {h: _snapshot(conn, _run_near(conn, self.t - dt.timedelta(hours=h))) for h in (24, 72, 168)}
        self.days = [(self.t - dt.timedelta(days=d)).strftime("%Y-%m-%d") for d in range(6, -1, -1)]
        self.history_hours = 0
        first = conn.execute("SELECT MIN(started_at) FROM runs WHERE status IN ('ok','partial')").fetchone()[0]
        if first:
            self.history_hours = (self.t - parse_iso(first)).total_seconds() / 3600

    def age(self, uid):
        g = self.games.get(uid)
        return _age_days(g["created_at"], self.t) if g else None

    def playing(self, uid):
        return self.now_map.get(uid) or 0

    def growth(self, uids, hours):
        return _growth(self.now_map, self.then[hours], uids)

    def daily_totals(self, uids):
        if not uids:
            return []
        marks = ",".join(str(int(u)) for u in uids)
        rows = dict(self.conn.execute(
            f"SELECT day, SUM(peak_playing) FROM daily WHERE universe_id IN ({marks}) AND day >= ? GROUP BY day",
            (self.days[0],)).fetchall())
        return [rows.get(d) for d in self.days]

    def analyse(self):
        r, t = self.r, self.t
        window_start = iso(t - dt.timedelta(days=r["wave_window_days"]))
        surface = collections.defaultdict(collections.Counter)
        all_term = collections.defaultdict(set)
        young_term = collections.defaultdict(set)
        self.game_terms = {}
        for uid, g in self.games.items():
            ts = terms_of(g["name"], self.generic, surface)
            self.game_terms[uid] = ts
            young = bool(g["created_at"] and g["created_at"] >= window_start)
            for x in ts:
                all_term[x].add(uid)
                if young:
                    young_term[x].add(uid)
        self.surface, self.young_term, self.all_term = surface, young_term, all_term

        # A word is "new" if most of the games using it that still have players are young.
        # Dead old games don't count, so a revived theme (ragdoll in 2020 and again now) still shows up.
        def novelty(x):
            old_active = sum(1 for u in all_term[x] - young_term[x]
                             if (self.games[u]["last_playing"] or 0) >= r["novelty_old_min_playing"])
            return len(young_term[x]) / (len(young_term[x]) + old_active)
        self.novelty = novelty
        cands = [x for x, ys in young_term.items() if len(ys) >= r["min_games"] and novelty(x) >= r["min_novelty"]]
        cands.sort(key=lambda x: (-len(young_term[x]), " " in x, x))
        # Group terms. A term mostly inside an existing group joins it when it's a word pair
        # ("ragdoll physics" -> ragdoll) or a similar size. A much smaller pocket inside a big
        # group ("evolution" inside "+1") stays separate as a child, and is only shown if it's
        # hotter than its parent, which is exactly the kind of opening worth seeing.
        groups = []
        for x in cands:
            ys = young_term[x]
            merged, parent = False, None
            for grp in groups:
                inter = len(ys & grp["members"])
                contained = inter / min(len(ys), len(grp["members"])) >= r["merge_containment"]
                same_games = inter / len(ys | grp["members"]) >= r["merge_jaccard"]
                if (contained and " " in x) or same_games:
                    grp["terms"].append(x)
                    grp["members"] |= ys
                    merged = True
                    break
                if contained:
                    parent = parent or grp
            if not merged:
                groups.append({"terms": [x], "members": set(ys), "parent": parent})

        measured = {id(grp): self._measure(grp) for grp in groups}
        waves = []
        for grp in groups:
            w = measured[id(grp)]
            if grp["parent"] is not None:
                pw = measured[id(grp["parent"])]
                w["parent"] = pw["label"]
                if not (w["stage"] in ("jump", "starting") and pw["stage"] not in ("jump", "starting")):
                    if w["label"] not in pw["terms"]:
                        pw["terms"].append(w["label"])   # still listed, just not as its own wave
                    continue  # says nothing its parent doesn't
            waves.append(w)
        order = {s: i for i, s in enumerate(STAGES)}
        waves.sort(key=lambda w: (order[w["stage"]], -w["score"]))
        self.waves = waves
        self.lone = self._lone_breakouts(waves)
        return waves

    def _measure(self, grp):
        r, t = self.r, self.t
        members = grp["members"]
        # Label: a word pair that covers most of the wave beats the single word.
        label_term = grp["terms"][0]
        for x in grp["terms"]:
            if " " in x and len(self.young_term[x] & members) >= 0.7 * len(members):
                label_term = x
                break
        pool = set(members) | self.all_term[grp["terms"][0]]
        leader = max(pool, key=self.playing)
        everyone = set(members) | {leader}
        followers = [u for u in members if u != leader]
        eligible = [u for u in followers if (self.age(u) or 0) >= 3]
        hits = [u for u in eligible if (self.games[u]["peak_playing"] or 0) >= 1000]
        recent = [u for u in eligible if (self.age(u) or 99) <= 17]
        recent_hits = [u for u in recent if (self.games[u]["peak_playing"] or 0) >= 1000]
        hits10 = [u for u in eligible if (self.games[u]["peak_playing"] or 0) >= 10000]
        n7 = sum(1 for u in members if (self.age(u) or 99) <= 7)
        n14 = sum(1 for u in members if (self.age(u) or 99) <= 14)
        total = sum(self.playing(u) for u in everyone)
        genres = collections.Counter(
            " / ".join(x for x in (self.games[u]["genre_l1"], self.games[u]["genre_l2"]) if x) or "unknown"
            for u in members)
        lineage_l2 = set(self.r["lineage_subgenres"])
        lineage = sum(1 for u in members if self.games[u]["genre_l2"] in lineage_l2) >= 0.5 * len(members)
        m = {
            "key": grp["terms"][0],
            "label": display(label_term, self.surface),
            "terms": [display(x, self.surface) for x in grp["terms"]],
            "members": sorted(members, key=self.playing, reverse=True),
            "n": len(members), "n7": n7, "n14": n14,
            "leader": leader, "leader_playing": self.playing(leader), "leader_age": self.age(leader),
            "leader_growth_24h": self.growth([leader], 24), "leader_growth_72h": self.growth([leader], 72),
            "eligible": len(eligible), "hits": len(hits), "hits10": len(hits10),
            "hit_rate": (len(hits) / len(eligible)) if eligible else None,
            "recent": len(recent), "recent_hits": len(recent_hits),
            "recent_hit_rate": (len(recent_hits) / len(recent)) if recent else None,
            "total": total,
            "growth_24h": self.growth(everyone, 24), "growth_72h": self.growth(everyone, 72),
            "growth_7d": self.growth(everyone, 168),
            "concentration": (self.playing(leader) / total) if total else None,
            "spark": sparkline(self.daily_totals(everyone)),
            "best": sorted(followers, key=self.playing, reverse=True)[:4],
            "newest": sorted([u for u in members if (self.age(u) or 99) <= 7], key=self.playing, reverse=True)[:3],
            "genre": genres.most_common(1)[0][0] if genres else "unknown",
            "lineage": lineage,
            "parent": None,
        }
        m["stage"], m["why"] = self._stage(m)
        # Rank within a stage: successful copies, fresh leader, growing.
        fresh = max(0.0, 1 - (m["leader_age"] or 90) / 90)
        m["score"] = (sum(self.playing(u) for u in followers) + 1) * (0.5 + fresh) * (m["growth_72h"] or 1)
        return m

    def _stage(self, m):
        r = self.r
        age = m["leader_age"] if m["leader_age"] is not None else 999
        g7, g3 = m["growth_7d"], m["growth_72h"]
        if g7 is not None and g7 < r["fading_7d"]:
            return "fading", f"players down {100 - g7 * 100:.0f}% in a week"
        if m["eligible"] >= 10 and m["hit_rate"] is not None and m["hit_rate"] < r["crowded_hit_rate"]:
            return "crowded", f"only {m['hits']} of {m['eligible']} copies reached 1K players"
        if m["recent"] >= 6 and m["recent_hit_rate"] < r["crowded_hit_rate"]:
            return "crowded", (f"the newest copies are failing: {m['recent_hits']} of {m['recent']} "
                               f"from the last ~2 weeks reached 1K")
        if m["n"] >= r["crowded_games"]:
            return "crowded", f"{m['n']} games already"
        if age > r["crowded_age_days"]:
            return "crowded", f"the leader is {age:.0f} days old"
        cooling = g3 is not None and g3 < 0.85
        big_enough = m["leader_playing"] >= r["min_leader_playing"]
        if (m["hits"] >= r["jump_min_hits"] and (m["hit_rate"] or 0) >= r["jump_hit_rate"]
                and age <= r["jump_max_age_days"] and not cooling and big_enough
                and m["total"] >= r["jump_min_total"]):
            return "jump", (f"{m['hits']} of {m['eligible']} copies reached 1K+ players; "
                            f"leader is {age:.0f} days old; {m['n']} games so far")
        if (age <= r["starting_max_age_days"] and m["n"] <= r["starting_max_games"]
                and big_enough and not cooling):
            return "starting", f"leader is {age:.0f} days old with {m['n'] - 1} copies so far"
        if cooling:
            return "watching", f"players down {100 - g3 * 100:.0f}% in 3 days"
        return "watching", "not enough copies succeeding yet"

    def _lone_breakouts(self, waves):
        r = self.r
        covered = set()
        for w in waves:
            if w["stage"] != "watching":
                covered |= set(w["members"]) | {w["leader"]}
        out = []
        for uid, g in self.games.items():
            age = self.age(uid)
            if age is None or age > r["lone_max_age_days"] or uid in covered:
                continue
            if self.playing(uid) < r["lone_min_playing"]:
                continue
            copies = set()
            for x in self.game_terms.get(uid, ()):
                ys = self.young_term.get(x, set())
                if 1 < len(ys) <= 12 and self.novelty(x) >= self.r["min_novelty"]:
                    copies |= ys
            copies.discard(uid)
            copies = sorted(copies, key=self.playing, reverse=True)
            out.append({"uid": uid, "age": age, "playing": self.playing(uid),
                        "growth_24h": self.growth([uid], 24), "copies": copies[:3], "n_copies": len(copies),
                        "genre": " / ".join(x for x in (g["genre_l1"], g["genre_l2"]) if x) or "unknown"})
        out.sort(key=lambda x: x["playing"], reverse=True)
        return out[:25]

    def search_terms(self, limit=12):
        """Words to add to the next run's Roblox searches, so the small copies of hot waves
        and of lone breakouts get found too (charts only show the big ones)."""
        out = []
        for w in self.waves:
            if w["stage"] in ("jump", "starting") and w["label"] not in out:
                out.append(w["label"])
        for x in self.lone[:6]:
            words = [t for t in tokens(self.games[x["uid"]]["name"]) if t not in STOP][:3]
            q = " ".join(words)
            if q and q not in out:
                out.append(q)
        return out[:limit]

    # ---- state + alerts --------------------------------------------------------------

    def update_state(self):
        """Store each wave's stage; return alerts for waves that just entered jump/starting
        and for brand-new games that just crossed the lone-breakout alert threshold."""
        r, ts = self.r, iso(self.t)
        alerts = []
        # Quality gate: a thin or brand-new database overrates waves (it sees the winners
        # before the flops), so alerts wait for enough checks and games.
        n_runs = self.conn.execute("SELECT COUNT(*) FROM runs WHERE status IN ('ok','partial')").fetchone()[0]
        warmed_up = n_runs >= r["alert_min_runs"] and len(self.games) >= r["alert_min_games"]
        state = {row["wave"]: row for row in self.conn.execute("SELECT * FROM wave_state")}
        for w in self.waves:
            row = state.get(w["key"])
            if row is None:
                stage_runs = 1
                self.conn.execute("INSERT INTO wave_state (wave, stage, stage_since, stage_runs, last_seen)"
                                  " VALUES (?,?,?,1,?)", (w["key"], w["stage"], ts, ts))
            elif row["stage"] != w["stage"]:
                stage_runs = 1
                self.conn.execute("UPDATE wave_state SET stage = ?, stage_since = ?, stage_runs = 1, last_seen = ?"
                                  " WHERE wave = ?", (w["stage"], ts, ts, w["key"]))
            else:
                stage_runs = (row["stage_runs"] or 1) + 1
                self.conn.execute("UPDATE wave_state SET stage_runs = ?, last_seen = ? WHERE wave = ?",
                                  (stage_runs, ts, w["key"]))
            w["stage_runs"] = stage_runs
            already = row["alerted_stage"] if row else None
            loud_enough = w["stage"] == "jump" or w["leader_playing"] >= r["alert_starting_min_leader"]
            steady = stage_runs >= r["alert_min_stage_runs"]
            if (w["stage"] in ("jump", "starting") and already != w["stage"] and loud_enough
                    and steady and warmed_up):
                alerts.append({"kind": w["stage"], "key": f"wave:{w['key']}:{w['stage']}", "wave": w})
        latest = self.conn.execute(
            "SELECT started_at FROM runs WHERE status IN ('ok','partial') ORDER BY id DESC LIMIT 1").fetchone()
        if latest and warmed_up:
            lone_ids = {x["uid"]: x for x in self.lone}
            for e in self.conn.execute(
                    """SELECT universe_id, value FROM events WHERE kind = 'crossed' AND baseline = 0
                       AND value >= ? AND ts >= ?""", (r["alert_lone_playing"], latest["started_at"])):
                uid = e["universe_id"]
                if (self.age(uid) or 99) <= r["alert_lone_max_age_days"] and uid in lone_ids:
                    key = f"lone:{uid}:{e['value']}"
                    if not self.conn.execute("SELECT 1 FROM alerts_log WHERE key = ?", (key,)).fetchone():
                        alerts.append({"kind": "lone", "key": key, "lone": lone_ids[uid], "value": e["value"]})
        order = {"jump": 0, "starting": 1, "lone": 2}
        alerts.sort(key=lambda a: order[a["kind"]])
        alerts = alerts[:r["max_alerts_per_run"]]
        # Only alerts that will actually be sent are marked; the rest get another chance next run.
        for a in alerts:
            if "wave" in a:
                self.conn.execute("UPDATE wave_state SET alerted_stage = ?, alerted_at = ? WHERE wave = ?",
                                  (a["kind"], ts, a["wave"]["key"]))
        self.conn.commit()
        return alerts
