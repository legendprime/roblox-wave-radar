"""Where the money is. Roblox doesn't publish revenue, but it does publish the Top Earning
chart, in order. Reading that order against player counts shows which games earn far more per
player than usual: a game at #45 with 900 players earns about as much as its chart neighbours
with 18,000. Those are the games (and game types) worth studying when the goal is revenue, not
player count. For each one the radar also reads its public store: what it sells and for how much."""
import datetime as dt
import re
import statistics

# What a store item is, guessed from its name (first match wins). Rough, like the mechanics list.
CATEGORIES = [
    ("gifting", r"\bgift"),
    ("boosts (2x, auto, skip)", r"\b\d+x\b|\bx\d+\b|double|triple|boost|multiplier|faster|\bauto\b|instant|\bskip"),
    ("currency packs", r"cash|coins?\b|gems?\b|money|bucks|\bgold\b|diamonds?|tokens?\b|credits?\b|\byen\b|\$\s?\d"),
    ("starter packs / bundles", r"starter|bundle|\bpacks?\b|\bkit\b|\boffer"),
    ("random rolls (crates, spins, eggs)", r"\brolls?\b|\bspins?\b|crates?\b|\bcases?\b|\beggs?\b|luck|gacha|summon|"
                                           r"capsule|chests?\b|mystery|reroll"),
    ("VIP / passes", r"\bvip\b|premium|\bpass\b|season|member"),
    ("limited items", r"limited|exclusive"),
    ("revives / extra tries", r"reviv|respawn|extra li|continue|second chance"),
]
_CATS = [(name, re.compile(rx)) for name, rx in CATEGORIES]
OTHER = "items / unlocks"
JOKE_PRICE = 50000      # above this an item is a joke or a donation button, not part of the price ladder


def category(name, description=""):
    text = (name or "").lower()
    for cat, rx in _CATS:
        if rx.search(text):
            return cat
    if re.search(r"limited|only \d+ ", (description or "").lower()):
        return "limited items"
    return OTHER


def typical_players(playing, i, k):
    """Median players of the chart neighbours (k ranks either side, not counting the game itself)."""
    near = playing[max(0, i - k):i] + playing[i + 1:i + 1 + k]
    near = [p for p in near if p is not None]
    return statistics.median(near) if near else None


class Money:
    def __init__(self, radar, conn, cfg, insights):
        self.R, self.conn, self.cfg, self.I = radar, conn, cfg, insights
        self.m = cfg["money"]
        self.chart = self.m["chart"]
        self._rows = None
        self.start, self.history_days = None, 0

    def store(self, uid):
        f = self.conn.execute("SELECT * FROM store_fetch WHERE universe_id = ?", (uid,)).fetchone()
        if not f:
            return None
        items = self.conn.execute("SELECT kind, name, description, price FROM store_items WHERE universe_id = ? "
                                  "AND price > 0 AND price <= ?", (uid, JOKE_PRICE)).fetchall()
        gifts, core, cats = 0, [], {}
        for it in items:
            cat = category(it["name"], it["description"])
            if cat == "gifting":
                gifts += 1
                continue
            core.append(it)
            c = cats.setdefault(cat, {"name": cat, "n": 0, "max": 0})
            c["n"] += 1
            c["max"] = max(c["max"], it["price"])
        prices = sorted(it["price"] for it in core)
        top = sorted(core, key=lambda it: -it["price"])[:6]
        return {"n": len(core), "passes": sum(1 for it in core if it["kind"] == "pass"),
                "products": sum(1 for it in core if it["kind"] == "product"), "gifting": gifts > 0,
                "max": prices[-1] if prices else None, "median": round(statistics.median(prices)) if prices else None,
                "cats": sorted(cats.values(), key=lambda c: (-c["n"], -c["max"]))[:6],
                "top": [{"name": (it["name"] or "").strip()[:60], "price": it["price"]} for it in top],
                "more": bool(f["more"]), "fetched": f["fetched_at"]}

    def rows(self):
        if self._rows is not None:
            return self._rows
        R, c, m = self.R, self.conn, self.m
        self._rows = []
        if not self.I.latest_run:
            return self._rows
        chart = c.execute("SELECT universe_id, MIN(position) pos, playing FROM sort_hits WHERE run_id = ? AND sort_id = ? "
                          "GROUP BY universe_id ORDER BY pos", (self.I.latest_run, self.chart)).fetchall()
        chart = [r for r in chart if r["universe_id"] in R.games]
        playing = [r["playing"] for r in chart]
        hist = {r[0]: r for r in c.execute(
            "SELECT universe_id, MIN(day), COUNT(*), MIN(best_pos) FROM chart_days WHERE sort_id = ? GROUP BY universe_id",
            (self.chart,))}
        self.start = c.execute("SELECT MIN(day) FROM chart_days WHERE sort_id = ?", (self.chart,)).fetchone()[0]
        self.history_days = c.execute("SELECT COUNT(DISTINCT day) FROM chart_days WHERE sort_id = ?",
                                      (self.chart,)).fetchone()[0]
        new_cut = (R.t - dt.timedelta(days=m["new_days"])).strftime("%Y-%m-%d")
        for i, r in enumerate(chart):
            uid = r["universe_id"]
            typ = typical_players(playing, i, m["neighbours"])
            p = r["playing"] or 0
            h = hist.get(uid)
            first = h[1] if h else None
            self._rows.append({
                "uid": uid, "pos": r["pos"], "playing": p, "typical": round(typ) if typ else None,
                "multiple": round(typ / max(p, 100), 1) if typ else None,
                "age": R.age(uid), "first_day": first, "days_on": h[2] if h else 0, "best": h[3] if h else r["pos"],
                "new": bool(first and self.start and first > self.start and first >= new_cut),
                "type": R.games[uid]["genre_l2"] or R.games[uid]["genre_l1"] or "Other",
            })
        return self._rows

    def small(self):
        """On the earning chart with few players, biggest earnings per player first."""
        rows = [r for r in self.rows() if r["playing"] <= self.m["small_max_playing"] and r["multiple"]]
        return sorted(rows, key=lambda r: -r["multiple"])

    def young(self):
        return [r for r in self.rows() if r["age"] is not None and r["age"] <= self.m["young_days"]]

    def by_type(self):
        groups = {}
        for r in self.rows():
            if r["multiple"]:
                groups.setdefault(r["type"], []).append(r)
        out = []
        for name, rs in groups.items():
            if len(rs) < 2:
                continue
            out.append({"name": name, "n": len(rs),
                        "multiple": round(statistics.median(r["multiple"] for r in rs), 1),
                        "playing": round(statistics.median(r["playing"] for r in rs)),
                        "young": sum(1 for r in rs if r["age"] is not None and r["age"] <= self.m["young_days"]),
                        "best_pos": min(r["pos"] for r in rs),
                        "top": [r["uid"] for r in sorted(rs, key=lambda r: -r["multiple"])[:3]]})
        return sorted(out, key=lambda g: -g["multiple"])

    def store_games(self):
        """Games whose stores are worth reading, most useful first: small and young earners, then the rest."""
        rows = self.rows()
        young = {r["uid"] for r in self.young()}
        order = sorted(rows, key=lambda r: (r["uid"] not in young and r["playing"] > self.m["small_max_playing"],
                                            -(r["multiple"] or 0)))
        return [r["uid"] for r in order]

    def key_games(self, limit=40):
        """Small and young earners get full details, badges and creators like other key games."""
        seen, out = set(), []
        for r in self.young() + self.small():
            if r["uid"] not in seen:
                seen.add(r["uid"])
                out.append(r["uid"])
        return out[:limit]

    def alerts(self, warmed_up):
        """A young game that just reached the earning chart for the first time."""
        m = self.m
        rows = self.rows()
        if not warmed_up or not rows or self.history_days < m["alert_min_chart_days"]:
            return []
        out = []
        # Alert within a day of the first appearance or not at all, so old entries never pile up.
        fresh = (self.R.t - dt.timedelta(days=1)).strftime("%Y-%m-%d")
        for r in sorted(rows, key=lambda r: r["pos"]):
            if not r["new"] or r["first_day"] < fresh or r["age"] is None or r["age"] > m["alert_max_age_days"]:
                continue
            key = f"money:{r['uid']}"
            if self.conn.execute("SELECT 1 FROM alerts_log WHERE key = ?", (key,)).fetchone():
                continue
            out.append({"kind": "money", "key": key, "row": r, "store": self.store(r["uid"])})
        return out[:m["max_alerts_per_run"]]
