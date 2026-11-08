"""Daily extra lookups for the games that matter (wave leaders, breakouts, your games):
badges (retention, progression and live-event stand-ins) and creators (group size, other
games). Runs on a time budget and rotates oldest-first, so it never slows the main check."""
import datetime as dt
import json
import time

from .api import ApiError
from .db import iso, now, norm_iso


def run(conn, cfg, api, key_games, log=print):
    e = cfg["enrich"]
    t0 = time.monotonic()
    ts = iso(now())
    badge_cut = iso(now() - dt.timedelta(hours=e["badge_refresh_hours"]))
    creator_cut = iso(now() - dt.timedelta(days=e["creator_refresh_days"]))
    fetched = {r[0]: r[1] for r in conn.execute("SELECT universe_id, fetched_at FROM badge_fetch")}
    todo_badges = sorted((u for u in key_games if (fetched.get(u) or "") < badge_cut), key=lambda u: fetched.get(u) or "")
    n_b = n_c = 0
    for uid in todo_badges:
        if time.monotonic() - t0 > e["budget_s"] * 0.6:
            break
        try:
            rows = api.badges(uid)
        except ApiError as ex:
            log(f"  ! badges {uid}: {ex}")
            continue
        conn.execute("DELETE FROM badges WHERE universe_id = ?", (uid,))
        conn.executemany("INSERT OR REPLACE INTO badges VALUES (?,?,?,?,?)",
                         [(uid, b.get("id"), b.get("name"), (b.get("statistics") or {}).get("awardedCount"),
                           norm_iso(b.get("created"))) for b in rows if b.get("id")])
        conn.execute("INSERT OR REPLACE INTO badge_fetch VALUES (?,?,?)", (uid, ts, len(rows)))
        n_b += 1
    conn.commit()

    marks = ",".join(str(int(u)) for u in key_games) or "0"
    by_game = {r[0]: (r[1], r[2]) for r in conn.execute(
        f"SELECT universe_id, creator_type, creator_id FROM games WHERE universe_id IN ({marks}) AND creator_id IS NOT NULL")}
    have = {(r[0], r[1]): r[2] for r in conn.execute("SELECT creator_type, creator_id, fetched_at FROM creators")}
    # Key games come most-important first (your games, wave leaders, breakouts), so their creators go first.
    todo_creators = []
    for u in key_games:
        c = by_game.get(u)
        if c and c not in todo_creators and (have.get(c) or "") < creator_cut:
            todo_creators.append(c)
    for ctype, cid in todo_creators:
        if time.monotonic() - t0 > e["budget_s"]:
            break
        try:
            if ctype == "Group":
                info = api.group(cid)
                name, members = info.get("name"), info.get("memberCount")
            else:
                name, members = None, api.followers(cid)
            games = api.creator_games(ctype, cid)
        except ApiError as ex:
            log(f"  ! creator {ctype} {cid}: {ex}")
            continue
        top = max(games, key=lambda g: g.get("placeVisits") or 0) if games else {}
        conn.execute("INSERT OR REPLACE INTO creators VALUES (?,?,?,?,?,?,?,?,?)",
                     (ctype, cid, name, members, len(games), sum(g.get("placeVisits") or 0 for g in games),
                      top.get("name"), top.get("placeVisits"), ts))
        n_c += 1
    conn.commit()
    left_b = max(0, len(todo_badges) - n_b)
    left_c = max(0, len(todo_creators) - n_c)
    log(f"enrich: badges for {n_b} games, {n_c} creators in {time.monotonic() - t0:.0f}s"
        + (f" ({left_b} badge and {left_c} creator lookups continue next run)" if left_b or left_c else ""))


# ---- reading it back -------------------------------------------------------------------

def badge_summary(conn, uid, visits, t):
    """Retention / progression / live-event stand-ins from a game's badges, or None."""
    rows = conn.execute("SELECT name, awarded, created FROM badges WHERE universe_id = ? AND awarded IS NOT NULL "
                        "ORDER BY awarded DESC", (uid,)).fetchall()
    if not rows or not rows[0]["awarded"]:
        return None
    entry = rows[0]
    out = {"entry_badge": entry["name"], "players": entry["awarded"],
           "visits_per_player": round(visits / entry["awarded"], 1) if visits else None,
           "milestones": [], "events": []}
    recent = iso(t - dt.timedelta(days=21))
    for r in rows[1:]:
        share = r["awarded"] / entry["awarded"]
        item = {"name": r["name"], "awarded": r["awarded"], "share": round(share, 3)}
        if r["created"] and r["created"] >= recent:
            out["events"].append(item)          # added in the last 3 weeks: new content or an event
        elif len(out["milestones"]) < 4:
            out["milestones"].append(item)
    out["events"] = out["events"][:4]
    return out


def creator_info(conn, ctype, cid, big_members):
    if cid is None:
        return None
    r = conn.execute("SELECT * FROM creators WHERE creator_type = ? AND creator_id = ?", (ctype, cid)).fetchone()
    if not r:
        return None
    return {"name": r["name"], "type": ctype, "members": r["members"], "n_games": r["n_games"],
            "top_game": r["top_game"], "top_visits": r["top_visits"],
            "big": bool(r["members"] and r["members"] >= big_members)}


def save_key_games(conn, uids):
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('key_games', ?)", (json.dumps(sorted(uids)),))
    conn.commit()
