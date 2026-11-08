"""Run with: python3 -m unittest discover -s tests"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from tracker import config, db, insights, waves


class InsightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "t.sqlite")
        self.cfg = config.load()
        self.t = db.now()
        # Tracking "started" 20 days ago, so copies made since then count for the track record.
        self.conn.execute("INSERT INTO runs (started_at, status) VALUES (?, 'ok')",
                          (db.iso(self.t - dt.timedelta(days=20)),))
        self.conn.execute("INSERT INTO runs (started_at, status) VALUES (?, 'ok')", (db.iso(self.t),))
        self.uid = 1

    def add(self, name, age_days, playing, desc="", l2="Tycoon"):
        uid = self.uid
        self.uid += 1
        created = db.iso(self.t - dt.timedelta(days=age_days))
        self.conn.execute(
            "INSERT INTO games (universe_id, name, description, created_at, last_playing, peak_playing, genre_l1, genre_l2)"
            " VALUES (?,?,?,?,?,?,'Simulation',?)", (uid, name, desc, created, playing, playing, l2))
        self.conn.execute("INSERT INTO snapshots (run_id, ts, universe_id, playing) VALUES (2,?,?,?)",
                          (db.iso(self.t), uid, playing))
        self.conn.execute("INSERT INTO daily VALUES (?,?,?,NULL)", (uid, created[:10], playing))
        return uid

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_mechanics_from_description(self):
        uid = self.add("Steal An Egg", 30, 5000, desc="Train on the treadmill. Hatch eggs. Earn money offline!")
        self.conn.commit()
        radar = waves.Radar(self.conn, self.cfg, t=self.t)
        found = insights.Insights(radar, self.conn, self.cfg).mechanics(uid)
        for m in ("stealing", "training / treadmill", "eggs / hatching", "offline earnings"):
            self.assertIn(m, found)
        self.assertNotIn("ragdoll physics", found)

    def test_track_record_uses_stage_on_launch_day(self):
        leader = self.add("Wobble Physics", 25, 40000, l2="Physics Sim")
        for i, p in enumerate([9000, 5000, 3000, 1500]):
            self.add(f"Wobble Arena {i}", 22 - i, p, l2="Physics Sim")
        late = self.add("Wobble Arena late", 16, 2000, l2="Physics Sim")   # made after tracking began
        # The wave was already "jump" on the late copy's launch day.
        self.conn.execute("INSERT INTO wave_days VALUES (?,?,?,?,?,?,?,?)",
                          (db.iso(self.t - dt.timedelta(days=18))[:10], "wobble", "wobble", "jump", 5, 4, 4, 58000))
        self.conn.commit()
        radar = waves.Radar(self.conn, self.cfg, t=self.t)
        radar.analyse()
        ins = insights.Insights(radar, self.conn, self.cfg)
        ins.record_track()
        row = self.conn.execute("SELECT stage FROM copy_stage WHERE universe_id = ?", (late,)).fetchone()
        self.assertEqual(row["stage"], "jump")
        self.assertIsNone(self.conn.execute("SELECT 1 FROM copy_stage WHERE universe_id = ?", (leader,)).fetchone())
        tr = ins.track_record()
        jump = next(s for s in tr["stages"] if s["stage"] == "jump")
        self.assertEqual((jump["finished"], jump["hit1k"]), (1, 1))      # 16 days old, peaked at 2,000

    def test_opportunities_rank_and_scale(self):
        self.add("Wobble Physics", 20, 40000, l2="Physics Sim")
        for i, p in enumerate([9000, 5000, 3000, 1500]):
            self.add(f"Wobble Arena {i}", 10 + i, p, l2="Physics Sim")
        self.conn.commit()
        radar = waves.Radar(self.conn, self.cfg, t=self.t)
        radar.analyse()
        opps = insights.Insights(radar, self.conn, self.cfg).opportunities()
        self.assertTrue(opps)
        self.assertEqual(opps[0]["score"], 100)
        self.assertTrue(all(o["why"] for o in opps))


if __name__ == "__main__":
    unittest.main()
