"""Prediction log: write a prediction before the outcome is known, grade it from
the collected snapshots, and keep score (hit rate, Brier score, calibration)."""
import datetime as dt

from .db import iso, now, parse_iso


def add(conn, subject, threshold, probability, by=None, within_days=None,
        universe_id=None, note=None):
    if not (0.0 <= probability <= 1.0):
        raise ValueError("probability must be between 0 and 1 (e.g. 0.6)")
    if bool(by) == bool(within_days):
        raise ValueError("give exactly one of --by DATE or --within-days N")
    by_iso = None
    if by:
        t = dt.datetime.fromisoformat(by)
        if t.tzinfo is None:  # a plain date means the end of that day, local time
            if len(by) <= 10:
                t = t + dt.timedelta(days=1)
            t = t.astimezone()
        by_iso = iso(t)
    cur = conn.execute(
        "INSERT INTO predictions (made_at, subject, universe_id, threshold, by_date, within_days,"
        " probability, note) VALUES (?,?,?,?,?,?,?,?)",
        (iso(now()), subject, universe_id, int(threshold), by_iso, within_days, probability, note))
    conn.commit()
    return cur.lastrowid


def link(conn, pred_id, universe_id):
    conn.execute("UPDATE predictions SET universe_id = ? WHERE id = ?", (universe_id, pred_id))
    conn.commit()


def _window(conn, p):
    """(start, end) of the period the prediction is about, or None if unknown yet."""
    if p["by_date"]:
        return parse_iso(p["made_at"]), parse_iso(p["by_date"])
    g = conn.execute("SELECT created_at FROM games WHERE universe_id = ?",
                     (p["universe_id"],)).fetchone()
    if not g or not g["created_at"]:
        return None
    start = parse_iso(g["created_at"])
    return start, start + dt.timedelta(days=p["within_days"])


def grade(conn):
    """Grade every open prediction whose outcome is now known. Returns count graded."""
    t_now = now()
    graded = 0
    for p in conn.execute("SELECT * FROM predictions WHERE outcome IS NULL").fetchall():
        if p["universe_id"] is None:
            continue
        win = _window(conn, p)
        if not win:
            continue
        start, end = win
        peak = conn.execute(
            "SELECT MAX(playing) FROM snapshots WHERE universe_id = ? AND ts >= ? AND ts <= ?",
            (p["universe_id"], iso(start), iso(min(end, t_now)))).fetchone()[0]
        if peak is not None and peak >= p["threshold"]:
            outcome = 1                      # already hit, no need to wait
        elif t_now >= end:
            outcome = 0
        else:
            if peak is not None:
                conn.execute("UPDATE predictions SET actual_peak = ? WHERE id = ?", (peak, p["id"]))
            continue
        conn.execute("UPDATE predictions SET actual_peak = ?, outcome = ?, graded_at = ? WHERE id = ?",
                     (peak or 0, outcome, iso(t_now), p["id"]))
        graded += 1
    conn.commit()
    return graded


def scoreboard(conn):
    rows = conn.execute("SELECT probability, outcome FROM predictions WHERE outcome IS NOT NULL").fetchall()
    open_n = conn.execute("SELECT COUNT(*) FROM predictions WHERE outcome IS NULL").fetchone()[0]
    out = {"graded": len(rows), "open": open_n, "hits": sum(r["outcome"] for r in rows)}
    if rows:
        out["mean_prob"] = sum(r["probability"] for r in rows) / len(rows)
        out["brier"] = sum((r["probability"] - r["outcome"]) ** 2 for r in rows) / len(rows)
        buckets = []
        for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
            hi = lo + 0.2
            sel = [r for r in rows if lo <= r["probability"] < hi or (hi >= 1.0 and r["probability"] == 1.0)]
            if sel:
                buckets.append((f"{int(lo*100)}–{int(hi*100)}%", len(sel),
                                sum(r["outcome"] for r in sel) / len(sel)))
        out["buckets"] = buckets
    return out
