"""Run with: python3 -m unittest discover -s tests"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from tracker import config, db, ideas, insights, money, waves


class MoneyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "t.sqlite")
        self.cfg = config.load()
        self.t = db.now()
        self.conn.execute("INSERT INTO runs (started_at, status) VALUES (?, 'ok')", (db.iso(self.t),))
        self.day = db.iso(self.t)[:10]

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def add(self, uid, pos, playing, age_days=400, l2="Tycoon", first_day=None):
        created = db.iso(self.t - dt.timedelta(days=age_days))
        self.conn.execute(
            "INSERT INTO games (universe_id, name, created_at, last_playing, peak_playing, genre_l1, genre_l2)"
            " VALUES (?,?,?,?,?,'Simulation',?)", (uid, f"Game {uid}", created, playing, playing, l2))
        self.conn.execute("INSERT INTO sort_hits VALUES (1,?,?,?,?,?,?,0)",
                          (db.iso(self.t), "top-earning", "high_end_phone", pos, uid, playing))
        self.conn.execute("INSERT INTO chart_days VALUES ('top-earning',?,?,?,?)", (first_day or self.day, uid, pos, playing))

    def money(self):
        self.conn.commit()
        radar = waves.Radar(self.conn, self.cfg, t=self.t)
        return money.Money(radar, self.conn, self.cfg, insights.Insights(radar, self.conn, self.cfg))

    def test_small_game_among_big_neighbours_earns_more_per_player(self):
        for pos in range(1, 16):
            self.add(pos, pos, 20000)
        self.add(99, 16, 1000, age_days=30, l2="Vehicle Sim")
        for pos in range(17, 31):
            self.add(pos, pos, 20000)
        m = self.money()
        row = next(r for r in m.rows() if r["uid"] == 99)
        self.assertEqual(row["typical"], 20000)
        self.assertEqual(row["multiple"], 20.0)
        self.assertEqual(m.small()[0]["uid"], 99)
        self.assertEqual([r["uid"] for r in m.young()], [99])
        self.assertEqual(m.store_games()[0], 99)       # its store is read first

    def test_new_on_chart_needs_history_before_it(self):
        old_day = db.iso(self.t - dt.timedelta(days=5))[:10]
        for pos in range(1, 10):
            self.add(pos, pos, 20000, first_day=old_day)
        self.add(50, 10, 3000, age_days=20)            # first seen on the chart today
        m = self.money()
        rows = {r["uid"]: r for r in m.rows()}
        self.assertTrue(rows[50]["new"])
        self.assertFalse(rows[1]["new"])
        self.assertEqual(m.alerts(True), [])           # only 2 days of chart history: too early to alert
        mid_day = db.iso(self.t - dt.timedelta(days=2))[:10]
        self.conn.execute("INSERT INTO chart_days VALUES ('top-earning',?,1,1,20000)", (mid_day,))
        found = self.money().alerts(True)
        self.assertEqual([a["row"]["uid"] for a in found], [50])
        self.assertEqual(self.money().alerts(False), [])

    def test_store_summary_and_categories(self):
        self.assertEqual(money.category("2x Cash"), "boosts (2x, auto, skip)")
        self.assertEqual(money.category("Crate of Cash"), "currency packs")
        self.assertEqual(money.category("25 Rolls"), "random rolls (crates, spins, eggs)")
        self.assertEqual(money.category("Gift 25 rolls"), "gifting")
        self.assertEqual(money.category("Cursed Pine", "LIMITED - only 50 will ever exist!"), "limited items")
        self.assertEqual(money.category("Aurora Spruce"), money.OTHER)
        self.add(7, 1, 5000)
        items = [("pass", 1, "VIP", 199), ("product", 2, "25 Rolls", 1899), ("product", 3, "Gift 25 rolls", 1899),
                 ("product", 4, "Crate of Cash", 249), ("product", 5, "Free thing", 0),
                 ("product", 6, "yuh", 1000000000)]
        for kind, iid, name, price in items:
            self.conn.execute("INSERT INTO store_items VALUES (7,?,?,?,NULL,?,NULL)", (kind, iid, name, price))
        self.conn.execute("INSERT INTO store_fetch VALUES (7,?,1,4,0)", (db.iso(self.t),))
        st = self.money().store(7)
        self.assertEqual((st["n"], st["passes"], st["products"], st["max"], st["gifting"]), (3, 1, 2, 1899, True))
        self.assertEqual(st["top"][0]["name"], "25 Rolls")
        self.assertIsNone(self.money().store(8))

    def test_chart_history_keeps_best_position_of_the_day(self):
        sql = """INSERT INTO chart_days VALUES (?,?,?,?,?) ON CONFLICT (sort_id, day, universe_id) DO UPDATE SET
                 playing = CASE WHEN excluded.best_pos < best_pos THEN excluded.playing ELSE playing END,
                 best_pos = MIN(best_pos, excluded.best_pos)"""
        for pos, playing in [(40, 900), (31, 1200), (55, 700)]:
            self.conn.execute(sql, ("top-earning", self.day, 5, pos, playing))
        self.assertEqual(tuple(self.conn.execute("SELECT best_pos, playing FROM chart_days WHERE universe_id = 5").fetchone()),
                         (31, 1200))


class IdeaTests(unittest.TestCase):
    def test_title_matching_and_verdicts(self):
        idea = {"name": "Ragdoll hoops", "queries": ["ragdoll basketball"], "match": ["ragdoll", "basket|hoop|dunk"]}
        self.assertTrue(ideas.matches(idea, "[UPD] Ragdoll Hoops 🏀"))
        self.assertFalse(ideas.matches(idea, "Ragdoll Soccer"))
        self.assertEqual(ideas.verdict(0), "🟢 open, untried")
        self.assertEqual(ideas.verdict(40, attempts=5), "⚪ tried, none took off")
        self.assertEqual(ideas.verdict(450), "🟡 being tried, still small")
        self.assertEqual(ideas.verdict(4000), "🟠 taken (mid-size)")
        self.assertEqual(ideas.verdict(50000), "🔴 taken")

    def test_new_game_since_last_check_is_flagged(self):
        class FakeApi:
            def search(self, q, pages):
                return [{"universeId": 1, "name": "Ragdoll Hoops", "playerCount": 30, "rootPlaceId": 11},
                        {"universeId": 2, "name": "Ragdoll Dunk Arena", "playerCount": 2500, "rootPlaceId": 22},
                        {"universeId": 3, "name": "Steal An Egg", "playerCount": 800000, "rootPlaceId": 33}]

            def games(self, ids):
                return [{"id": i, "created": db.iso(db.now() - dt.timedelta(days=5))} for i in ids]
        idea = {"name": "Ragdoll hoops", "queries": ["ragdoll basketball"], "match": ["ragdoll", "basket|hoop|dunk"]}
        res = ideas.check(FakeApi(), [idea], previous={"Ragdoll hoops": [1]}, log=lambda *a: None)[0]
        self.assertEqual([g["uid"] for g in res["games"]], [2, 1])           # the unrelated giant is left out
        self.assertEqual(res["verdict"], "🟠 taken (mid-size)")
        self.assertEqual([g["uid"] for g in res["new_since_last"]], [2])
        self.assertEqual([g["uid"] for g in res["just_shipped"]], [2])
        self.assertIn("Ragdoll Dunk Arena", ideas.render([res], "now"))


if __name__ == "__main__":
    unittest.main()
