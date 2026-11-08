"""macOS notifications for big milestones by young games."""
import datetime as dt
import subprocess

from .db import iso, now


def pending(conn, cfg):
    a = cfg["alerts"]
    min_created = iso(now() - dt.timedelta(days=a["notify_max_age_days"]))
    marks = ",".join("?" * len(a["notify_thresholds"])) or "NULL"
    return conn.execute(
        f"""SELECT e.id, e.value, g.name FROM events e JOIN games g USING (universe_id)
            WHERE e.notified = 0 AND e.baseline = 0 AND e.kind = 'crossed'
              AND e.value IN ({marks}) AND g.created_at >= ?
            ORDER BY e.value DESC""",
        (*a["notify_thresholds"], min_created)).fetchall()


def send(conn, cfg, log=print):
    rows = pending(conn, cfg)
    # Everything else that is non-baseline is considered seen once a run has reported it.
    conn.execute("UPDATE events SET notified = 1 WHERE notified = 0 AND id NOT IN (%s)"
                 % (",".join(str(r["id"]) for r in rows) or "0"))
    if rows and cfg["alerts"]["notify"]:
        top = rows[0]
        if len(rows) == 1:
            msg = f"{top['name']} crossed {top['value']:,} players"
        else:
            names = ", ".join(r["name"] or "?" for r in rows[:3])
            msg = f"{len(rows)} new games hit milestones: {names}"
        try:
            # Pass text as arguments, never spliced into the script (game names are untrusted).
            subprocess.run(
                ["osascript", "-e", "on run argv", "-e",
                 "display notification (item 1 of argv) with title (item 2 of argv)",
                 "-e", "end run", msg[:220], "Roblox Trend Tracker"],
                check=False, timeout=15, capture_output=True)
            log(f"notified: {msg}")
        except (OSError, subprocess.SubprocessError) as e:
            log(f"  ! notification failed: {e}")
    if rows:
        conn.execute("UPDATE events SET notified = 1 WHERE id IN (%s)"
                     % ",".join(str(r["id"]) for r in rows))
    conn.commit()
    return len(rows)
