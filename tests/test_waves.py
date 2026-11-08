"""Run with: python3 -m unittest discover -s tests"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from tracker import config, db, waves


class TermTests(unittest.TestCase):
    def test_terms(self):
        t = waves.terms_of("[🎃] Throw Food For Animals!")
        self.assertIn("throw", t)
        self.assertIn("throw food", t)
        self.assertIn("for animal", t)          # plural folded
        self.assertNotIn("for", t)
        self.assertEqual(waves.terms_of("[X2🔥] Steal An Egg"), {"steal", "egg"})
        self.assertIn("+1", waves.terms_of("+1 Speed Keyboard Escape"))
        self.assertEqual(waves.terms_of("Сбеги от цунами"), set())

    def test_brackets_and_generic_words_ignored(self):
        t = waves.terms_of("[UPD 5] Ragdoll Simulator (BETA)")
        self.assertEqual(t, {"ragdoll"})

    def test_sparkline(self):
        self.assertEqual(waves.sparkline([1, 2, 3]), "▁▄█")
        self.assertEqual(waves.sparkline([5]), "")


class StageTests(unittest.TestCase):
    """Builds a small fake Roblox and checks each wave lands in the right stage."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "t.sqlite")
        self.cfg = config.load()
        self.t = db.now()
        self.conn.execute("INSERT INTO runs (started_at, status) VALUES (?, 'ok')", (db.iso(self.t),))
        uid = 1

        def add(name, age_days, playing, peak=None, l2="Tycoon"):
            nonlocal uid
            created = db.iso(self.t - dt.timedelta(days=age_days))
            self.conn.execute(
                "INSERT INTO games (universe_id, name, created_at, last_playing, peak_playing, genre_l1, genre_l2)"
                " VALUES (?,?,?,?,?,'Simulation',?)", (uid, name, created, playing, peak or playing, l2))
            self.conn.execute("INSERT INTO snapshots (run_id, ts, universe_id, playing) VALUES (1,?,?,?)",
                              (db.iso(self.t), uid, playing))
            uid += 1

        # A hot wave: young leader, most copies succeed.
        add("Wobble Physics", 20, 40000, l2="Physics Sim")
        for i, p in enumerate([9000, 5000, 3000, 1500, 400]):
            add(f"Wobble Arena {i}", 10 + i, p, l2="Physics Sim")
        # A crowded wave: 30 copies, almost all fail.
        add("Juggle Food For Ducks", 50, 300000)
        for i in range(30):
            add(f"Juggle Thing {i}", 20 + i % 10, 50)
        # A lone breakout with no copies.
        add("Moon Vacuum Tycoon", 12, 25000)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_stages(self):
        radar = waves.Radar(self.conn, self.cfg, t=self.t)
        found = {w["key"]: w for w in radar.analyse()}
        self.assertEqual(found["wobble"]["stage"], "jump")
        self.assertFalse(found["wobble"]["lineage"])
        self.assertEqual(found["juggle"]["stage"], "crowded")
        self.assertIn("Moon Vacuum Tycoon", [radar.games[x["uid"]]["name"] for x in radar.lone])

    def _check(self):
        radar = waves.Radar(self.conn, self.cfg, t=self.t)
        radar.analyse()
        return [a["key"] for a in radar.update_state()]

    def test_alerts_wait_for_a_steady_stage_then_fire_once(self):
        self.cfg["radar"].update(alert_min_runs=0, alert_min_games=0, alert_min_stage_runs=2)
        self.assertNotIn("wave:wobble:jump", self._check())   # first sighting: wait
        self.assertIn("wave:wobble:jump", self._check())      # held for 2 checks: alert
        self.assertNotIn("wave:wobble:jump", self._check())   # already alerted

    def test_no_alerts_from_a_thin_database(self):
        self.cfg["radar"].update(alert_min_runs=3, alert_min_games=0, alert_min_stage_runs=1)
        self.assertEqual(self._check(), [])                   # only 1 check so far

    def test_search_terms_include_hot_waves(self):
        radar = waves.Radar(self.conn, self.cfg, t=self.t)
        radar.analyse()
        self.assertTrue(any(q.startswith("wobble") for q in radar.search_terms()))


if __name__ == "__main__":
    unittest.main()
