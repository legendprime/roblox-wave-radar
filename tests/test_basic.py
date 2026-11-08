"""Run with: python3 -m unittest discover -s tests"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from tracker import db, predict, report


class TimeTests(unittest.TestCase):
    def test_parse_roblox_timestamps(self):
        self.assertEqual(db.norm_iso("2026-07-25T07:50:51.492Z"), "2026-07-25T07:50:51Z")
        self.assertEqual(db.norm_iso("2026-07-25T07:50:51.4923456Z"), "2026-07-25T07:50:51Z")
        self.assertEqual(db.norm_iso("2026-07-25T07:50:51Z"), "2026-07-25T07:50:51Z")
        self.assertIsNone(db.norm_iso(None))

    def test_compact(self):
        self.assertEqual(report.compact(1179599), "1.18M")
        self.assertEqual(report.compact(116042), "116K")
        self.assertEqual(report.compact(28809), "28.8K")
        self.assertEqual(report.compact(5244), "5,244")
        self.assertEqual(report.compact(None), "—")


class PredictTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "t.sqlite")
        t = db.now()
        self.conn.execute("INSERT INTO games (universe_id, name, created_at) VALUES (1, 'A', ?)",
                          (db.iso(t - dt.timedelta(days=3)),))
        for i, playing in enumerate([100, 900, 4000]):
            ts = db.iso(t - dt.timedelta(hours=10 - i))
            self.conn.execute("INSERT INTO snapshots (run_id, ts, universe_id, playing) VALUES (?,?,1,?)",
                              (i + 1, ts, playing))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_hit_is_graded_early(self):
        pid = predict.add(self.conn, "A", 1000, 0.5, within_days=14, universe_id=1)
        self.assertEqual(predict.grade(self.conn), 1)
        p = self.conn.execute("SELECT * FROM predictions WHERE id = ?", (pid,)).fetchone()
        self.assertEqual((p["outcome"], p["actual_peak"]), (1, 4000))

    def test_open_until_deadline(self):
        future = (db.now() + dt.timedelta(days=5)).date().isoformat()
        predict.add(self.conn, "A", 10000, 0.2, by=future, universe_id=1)
        self.assertEqual(predict.grade(self.conn), 0)

    def test_miss_after_window(self):
        predict.add(self.conn, "A", 10000, 0.2, within_days=1, universe_id=1)
        self.assertEqual(predict.grade(self.conn), 1)
        sb = predict.scoreboard(self.conn)
        self.assertEqual((sb["graded"], sb["hits"]), (1, 0))
        self.assertAlmostEqual(sb["brier"], 0.04)

    def test_unlinked_concept_waits(self):
        predict.add(self.conn, "Concept", 10000, 0.3, within_days=7)
        self.assertEqual(predict.grade(self.conn), 0)

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            predict.add(self.conn, "A", 1, 1.5, within_days=3, universe_id=1)
        with self.assertRaises(ValueError):
            predict.add(self.conn, "A", 1, 0.5, universe_id=1)


if __name__ == "__main__":
    unittest.main()
