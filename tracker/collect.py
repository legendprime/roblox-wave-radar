"""One collection run: pull charts and search results, refresh tracked games,
store snapshots, and record milestone events.

Player counts come straight from the chart and search listings. The slow,
rate-limited details endpoint is only called for games that need it: new games,
the watchlist, tracked games that didn't show up in this run's listings, and a
rotating batch whose visits/metadata are oldest.
"""
import datetime as dt
import json

from .api import ApiError
from .config import watchlist
from .db import iso, norm_iso, now


def run_collect(conn, cfg, api, log=print):
    c = cfg["collect"]
    a = cfg["alerts"]
    started = now()
    ts = iso(started)
    day = ts[:10]
    first_run = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE status IN ('ok', 'partial')").fetchone()[0] == 0
    run_id = conn.execute("INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                          (ts,)).lastrowid
    conn.commit()
    errors = []
    seen = {}          # universe_id -> listing info (name, place, via, playing, votes)
    sort_rows, search_rows = [], []

    def remember(g, via):
        uid = g.get("universeId")
        if not uid:
            return None
        p = g.get("playerCount")
        e = seen.get(uid)
        if e is None:
            seen[uid] = {"name": g.get("name"), "root_place_id": g.get("rootPlaceId"), "via": via,
                         "playing": p, "up": g.get("totalUpVotes"), "down": g.get("totalDownVotes")}
        elif p is not None and (e["playing"] is None or p > e["playing"]):
            e["playing"] = p
        return uid

    # 1. Charts -------------------------------------------------------------
    for device in c["devices"]:
        try:
            n = 0
            for s in api.sorts(device, c["country"]):
                for pos, g in enumerate(s.get("games") or [], 1):
                    uid = remember(g, f"sort:{s['sortId']}")
                    if uid:
                        sort_rows.append((run_id, ts, s["sortId"], device, pos, uid,
                                          g.get("playerCount"), int(bool(g.get("isSponsored")))))
                        n += 1
            log(f"charts/{device}: {n} entries")
        except ApiError as e:
            errors.append(f"charts/{device}: {e}")
            log(f"  ! charts/{device}: {e}")

    # 2. Search -------------------------------------------------------------
    # Fixed queries from config.toml, plus the words of currently hot waves that the
    # radar saved last run (so small copies of a new wave get found, not just the leaders).
    row = conn.execute("SELECT value FROM meta WHERE key = 'dynamic_queries'").fetchone()
    dynamic = json.loads(row[0]) if row and row[0] else []
    queries = list(dict.fromkeys([q.lower() for q in c["queries"]] + [q.lower() for q in dynamic]))
    for q in queries:
        try:
            pos = 0
            for g in api.search(q, c["search_pages"]):
                uid = remember(g, f"search:{q}")
                if uid:
                    pos += 1
                    search_rows.append((run_id, ts, q, pos, uid, g.get("playerCount"),
                                        int(bool(g.get("isSponsored")))))
        except ApiError as e:
            errors.append(f"search/{q}: {e}")
            log(f"  ! search '{q}': {e}")
    log(f"search: {len(search_rows)} results over {len(queries)} queries ({len(dynamic)} from hot waves); "
        f"{len(seen)} distinct games seen this run")

    conn.executemany("INSERT OR IGNORE INTO sort_hits VALUES (?,?,?,?,?,?,?,?)", sort_rows)
    conn.executemany("INSERT OR IGNORE INTO search_hits VALUES (?,?,?,?,?,?,?)", search_rows)

    # 3. Register games ---------------------------------------------------
    existing = {r[0] for r in conn.execute("SELECT universe_id FROM games")}
    watch = watchlist(conn, cfg)
    new_ids = []
    for uid, info in seen.items():
        if uid in existing:
            conn.execute("UPDATE games SET last_seen_at = ? WHERE universe_id = ?", (ts, uid))
        else:
            conn.execute(
                "INSERT INTO games (universe_id, name, root_place_id, first_seen_at, first_seen_via,"
                " last_seen_at) VALUES (?,?,?,?,?,?)",
                (uid, info["name"], info["root_place_id"], ts, info["via"], ts))
            new_ids.append(uid)
    for uid in watch:
        if uid not in existing and uid not in seen:
            conn.execute("INSERT INTO games (universe_id, first_seen_at, first_seen_via)"
                         " VALUES (?,?,'watchlist')", (uid, ts))
            new_ids.append(uid)
    # Commit before the slow network phase so no write transaction is held while waiting on Roblox.
    conn.commit()

    # 4. Decide which games need the details endpoint ---------------------
    meta = {r["universe_id"]: r for r in conn.execute(
        "SELECT universe_id, meta_refreshed_at, last_refreshed_at FROM games")}
    need = {uid for uid in seen if not meta[uid]["meta_refreshed_at"]} | set(watch)
    young_cut = iso(started - dt.timedelta(days=c["keep_new_days"]))
    for r in conn.execute(
            "SELECT universe_id FROM games WHERE last_playing >= ? OR (first_seen_at >= ? AND last_playing >= ?)",
            (c["unseen_refresh_min_playing"], young_cut, c["min_track_playing"])):
        if r[0] not in seen:
            need.add(r[0])
    rotation = sorted((u for u in seen if u not in need), key=lambda u: meta[u]["meta_refreshed_at"] or "")
    need |= set(rotation[:c["meta_refresh_per_run"]])
    need = sorted(need)

    prior = {r["universe_id"]: r for r in conn.execute(
        "SELECT universe_id, last_refreshed_at FROM games")}

    # 5. Details + votes ----------------------------------------------------
    details, votes = [], {}
    try:
        details = api.games(need)
    except ApiError as e:
        errors.append(f"games: {e}")
        log(f"  ! games: {e}")
    unseen = [u for u in need if u not in seen]
    if unseen:
        try:
            votes = api.votes(unseen)
        except ApiError as e:
            errors.append(f"votes: {e}")
            log(f"  ! votes: {e}")

    # Assemble this run's snapshot: listings first, details override.
    snap = {uid: {"playing": e["playing"] or 0, "visits": None, "favorites": None,
                  "up": e["up"], "down": e["down"]} for uid, e in seen.items()}
    for d in details:
        uid = d["id"]
        creator = d.get("creator") or {}
        s = snap.setdefault(uid, {"playing": 0, "visits": None, "favorites": None, "up": None, "down": None})
        s["playing"] = d.get("playing") or 0
        s["visits"] = d.get("visits")
        s["favorites"] = d.get("favoritedCount")
        name = d.get("name")
        conn.execute(
            """UPDATE games SET root_place_id = ?, name = ?, description = ?, creator_id = ?,
               creator_name = ?, creator_type = ?, creator_verified = ?, created_at = ?,
               updated_at = ?, genre_l1 = ?, genre_l2 = ?, max_players = ?,
               meta_refreshed_at = ?, last_visits = ?, last_favorites = ?
               WHERE universe_id = ?""",
            (d.get("rootPlaceId"), name, d.get("description"), creator.get("id"),
             creator.get("name"), creator.get("type"), int(bool(creator.get("hasVerifiedBadge"))),
             norm_iso(d.get("created")), norm_iso(d.get("updated")), d.get("genre_l1"),
             d.get("genre_l2"), d.get("maxPlayers"), ts, d.get("visits"), d.get("favoritedCount"), uid))
        if name:
            conn.execute("INSERT OR IGNORE INTO name_history VALUES (?,?,?)", (uid, name, ts))
    for uid, (up, down) in votes.items():
        if uid in snap:
            snap[uid]["up"], snap[uid]["down"] = up, down
    for uid, info in seen.items():
        if info["name"]:
            conn.execute("UPDATE games SET name = COALESCE(name, ?) WHERE universe_id = ?", (info["name"], uid))

    # 6. Store snapshots, daily peaks, milestones -------------------------
    crossed = {(r[0], r[1]) for r in conn.execute(
        "SELECT universe_id, value FROM events WHERE kind = 'crossed'")}
    n_events = 0
    for uid, s in snap.items():
        playing = s["playing"]
        conn.execute(
            """UPDATE games SET last_refreshed_at = ?, last_playing = ?,
               peak_playing_at = CASE WHEN ? > COALESCE(peak_playing, 0) THEN ? ELSE peak_playing_at END,
               peak_playing = MAX(COALESCE(peak_playing, 0), ?) WHERE universe_id = ?""",
            (ts, playing, playing, ts, playing, uid))
        conn.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?)",
                     (run_id, ts, uid, playing, s["visits"], s["favorites"], s["up"], s["down"]))
        conn.execute(
            """INSERT INTO daily (universe_id, day, peak_playing, visits) VALUES (?,?,?,?)
               ON CONFLICT (universe_id, day) DO UPDATE SET
                 peak_playing = MAX(COALESCE(peak_playing, 0), excluded.peak_playing),
                 visits = COALESCE(excluded.visits, visits)""",
            (uid, day, playing, s["visits"]))
        p = prior.get(uid)
        had_prior = bool(p and p["last_refreshed_at"])
        for t in a["thresholds"]:
            if playing >= t and (uid, t) not in crossed:
                conn.execute(
                    "INSERT OR IGNORE INTO events (ts, universe_id, kind, value, detail, baseline)"
                    " VALUES (?,?,'crossed',?,?,?)",
                    (ts, uid, t, "while_tracked" if had_prior else "first_seen_above", int(first_run)))
                crossed.add((uid, t))
                n_events += 1

    alert_sorts = set(a["sorts"])
    for (_, _, sort_id, _, _, uid, _, _) in sort_rows:
        if sort_id in alert_sorts:
            cur = conn.execute(
                "INSERT OR IGNORE INTO events (ts, universe_id, kind, value, detail, baseline)"
                " VALUES (?,?,'entered_sort',0,?,?)", (ts, uid, sort_id, int(first_run)))
            n_events += cur.rowcount

    status = "ok" if not errors else ("partial" if snap else "failed")
    conn.execute(
        """UPDATE runs SET finished_at = ?, status = ?, requests = ?, n_sort_hits = ?,
           n_search_hits = ?, n_refreshed = ?, n_new_games = ?, errors = ? WHERE id = ?""",
        (iso(now()), status, api.requests, len(sort_rows), len(search_rows), len(snap),
         len(new_ids), "\n".join(errors) or None, run_id))
    conn.commit()
    log(f"snapshot of {len(snap)} games ({len(details)} via details, {len(new_ids)} new), "
        f"{n_events} events, {api.requests} requests, status {status}"
        + (" [first run: events marked as baseline]" if first_run else ""))
    return {"run_id": run_id, "status": status, "errors": errors, "first_run": first_run}
