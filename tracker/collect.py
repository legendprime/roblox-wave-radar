"""One collection run: pull charts and search results, refresh tracked games,
store snapshots, and record milestone events."""
import datetime as dt

from .api import ApiError
from .config import watchlist
from .db import iso, norm_iso, now


def run_collect(conn, cfg, api, log=print):
    c = cfg["collect"]
    a = cfg["alerts"]
    started = now()
    ts = iso(started)
    first_run = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE status IN ('ok', 'partial')").fetchone()[0] == 0
    run_id = conn.execute("INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                          (ts,)).lastrowid
    conn.commit()
    errors = []
    seen = {}          # universe_id -> {"name", "root_place_id", "via"}
    sort_rows, search_rows = [], []

    def remember(g, via):
        uid = g.get("universeId")
        if uid and uid not in seen:
            seen[uid] = {"name": g.get("name"), "root_place_id": g.get("rootPlaceId"), "via": via}
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
    for q in c["queries"]:
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
    log(f"search: {len(search_rows)} results over {len(c['queries'])} queries; "
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

    # 4. Decide what to refresh ------------------------------------------
    cutoff = iso(started - dt.timedelta(days=c["keep_new_days"]))
    refresh = set(seen) | set(watch)
    for r in conn.execute(
            "SELECT universe_id FROM games WHERE last_playing >= ? OR first_seen_at >= ?",
            (c["min_track_playing"], cutoff)):
        refresh.add(r[0])
    refresh = sorted(refresh)

    prior = {r["universe_id"]: r for r in conn.execute(
        "SELECT universe_id, name, last_refreshed_at, peak_playing FROM games")}

    # 5. Details + votes ----------------------------------------------------
    details, votes = [], {}
    try:
        details = api.games(refresh)
    except ApiError as e:
        errors.append(f"games: {e}")
        log(f"  ! games: {e}")
    try:
        votes = api.votes(refresh)
    except ApiError as e:
        errors.append(f"votes: {e}")
        log(f"  ! votes: {e}")

    crossed = {(r[0], r[1]) for r in conn.execute(
        "SELECT universe_id, value FROM events WHERE kind = 'crossed'")}
    n_events = 0
    for d in details:
        uid = d["id"]
        playing = d.get("playing") or 0
        creator = d.get("creator") or {}
        p = prior.get(uid)
        up, down = votes.get(uid, (None, None))
        name = d.get("name")
        conn.execute(
            """UPDATE games SET root_place_id = ?, name = ?, description = ?, creator_id = ?,
               creator_name = ?, creator_type = ?, creator_verified = ?, created_at = ?,
               updated_at = ?, genre_l1 = ?, genre_l2 = ?, max_players = ?,
               last_refreshed_at = ?, last_playing = ?,
               peak_playing_at = CASE WHEN ? > COALESCE(peak_playing, 0) THEN ? ELSE peak_playing_at END,
               peak_playing = MAX(COALESCE(peak_playing, 0), ?)
               WHERE universe_id = ?""",
            (d.get("rootPlaceId"), name, d.get("description"), creator.get("id"),
             creator.get("name"), creator.get("type"), int(bool(creator.get("hasVerifiedBadge"))),
             norm_iso(d.get("created")), norm_iso(d.get("updated")), d.get("genre_l1"),
             d.get("genre_l2"), d.get("maxPlayers"), ts, playing, playing, ts, playing, uid))
        if name:
            conn.execute("INSERT OR IGNORE INTO name_history VALUES (?,?,?)", (uid, name, ts))
        conn.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?)",
                     (run_id, ts, uid, playing, d.get("visits"), d.get("favoritedCount"), up, down))

        had_prior = bool(p and p["last_refreshed_at"])
        for t in a["thresholds"]:
            if playing >= t and (uid, t) not in crossed:
                conn.execute(
                    "INSERT OR IGNORE INTO events (ts, universe_id, kind, value, detail, baseline)"
                    " VALUES (?,?,'crossed',?,?,?)",
                    (ts, uid, t, "while_tracked" if had_prior else "first_seen_above",
                     int(first_run)))
                crossed.add((uid, t))
                n_events += 1

    alert_sorts = set(a["sorts"])
    for (_, _, sort_id, _, _, uid, _, _) in sort_rows:
        if sort_id in alert_sorts:
            cur = conn.execute(
                "INSERT OR IGNORE INTO events (ts, universe_id, kind, value, detail, baseline)"
                " VALUES (?,?,'entered_sort',0,?,?)", (ts, uid, sort_id, int(first_run)))
            n_events += cur.rowcount

    status = "ok" if not errors else ("partial" if details else "failed")
    conn.execute(
        """UPDATE runs SET finished_at = ?, status = ?, requests = ?, n_sort_hits = ?,
           n_search_hits = ?, n_refreshed = ?, n_new_games = ?, errors = ? WHERE id = ?""",
        (iso(now()), status, api.requests, len(sort_rows), len(search_rows), len(details),
         len(new_ids), "\n".join(errors) or None, run_id))
    conn.commit()
    log(f"refreshed {len(details)} games ({len(new_ids)} new), {n_events} events, "
        f"{api.requests} requests, status {status}"
        + (" [first run: events marked as baseline]" if first_run else ""))
    return {"run_id": run_id, "status": status, "errors": errors, "first_run": first_run}
