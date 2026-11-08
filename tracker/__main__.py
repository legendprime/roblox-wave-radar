"""Command line: python3 -m tracker <command>. Run with --help for the list."""
import argparse
import csv
import datetime as dt
import fcntl
import sys
import time

import json

from . import alerts, collect, config, dashboard, db, enrich, insights, notify, predict, report, site, waves
from . import api as api_mod


def log(msg):
    print(f"[{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


class RunLock:
    """Stops two collections running at once (e.g. a manual run during a scheduled one)."""
    def __enter__(self):
        db.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.f = open(db.DATA_DIR / ".lock", "w")
        try:
            fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("another collection is already running; skipping")
            sys.exit(0)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def resolve(conn, text, api=None):
    """Universe id from: a number, 'place:<placeId>', or part of a game name in the database."""
    text = str(text).strip()
    if text.isdigit():
        return int(text)
    if text.lower().startswith("place:"):
        api = api or api_mod.Api(log=log)
        uid = api.universe_for_place(text.split(":", 1)[1])
        if not uid:
            sys.exit(f"no game found for {text}")
        return int(uid)
    rows = conn.execute(
        "SELECT universe_id, name, last_playing FROM games WHERE name LIKE ? "
        "ORDER BY (LOWER(name) = LOWER(?)) DESC, last_playing DESC LIMIT 10",
        (f"%{text}%", text)).fetchall()
    if not rows:
        sys.exit(f"no game in the database matches '{text}'. Try: python3 -m tracker find '{text}' --online")
    if len(rows) == 1 or rows[0]["name"].lower() == text.lower():
        return rows[0]["universe_id"]
    print(f"'{text}' matches several games; use the id:")
    for r in rows:
        print(f"  {r['universe_id']:>12}  {report.compact(r['last_playing']):>8}  {r['name']}")
    sys.exit(1)


def cmd_run(args, conn, cfg):
    with RunLock():
        # Holding the lock means no other run is active: anything still marked running was cut off.
        conn.execute("UPDATE runs SET status = 'abandoned' WHERE status = 'running'")
        conn.commit()
        t0 = time.monotonic()
        api = api_mod.Api(log=log)
        try:
            result = collect.run_collect(conn, cfg, api, log=log)
        except Exception as e:
            conn.rollback()
            conn.execute("UPDATE runs SET status = 'failed', finished_at = ?, errors = ? "
                         "WHERE status = 'running'", (db.iso(db.now()), repr(e)))
            conn.commit()
            raise
        n = predict.grade(conn)
        if n:
            log(f"graded {n} prediction(s)")
        if not args.no_report:
            report.write_reports(conn, cfg, api, log=log)
        if sys.platform == "darwin":
            notify.send(conn, cfg, log=log)
        log(f"done in {time.monotonic() - t0:.0f}s ({api.rate_limited} rate-limit retries)")
        return 0 if result["status"] != "failed" else 1


def cmd_radar(args, conn, cfg):
    """What the GitHub workflow runs: collect, find waves, write the dashboard, send alerts."""
    with RunLock():
        conn.execute("UPDATE runs SET status = 'abandoned' WHERE status = 'running'")
        conn.commit()
        t0 = time.monotonic()
        api = api_mod.Api(log=log)
        if not args.no_collect:
            try:
                collect.run_collect(conn, cfg, api, log=log)
            except Exception as e:
                conn.rollback()
                conn.execute("UPDATE runs SET status = 'failed', finished_at = ?, errors = ? "
                             "WHERE status = 'running'", (db.iso(db.now()), repr(e)))
                conn.commit()
                raise
        db.compact(conn)
        predict.grade(conn)
        radar = waves.Radar(conn, cfg)
        radar.analyse()
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('dynamic_queries', ?)",
                     (json.dumps(radar.search_terms()),))
        conn.commit()
        found = radar.update_state() if not args.no_alerts else []
        # Key games get full details every run and daily badge/creator lookups.
        key = insights.Insights(radar, conn, cfg).key_games(
            insights.Insights(radar, conn, cfg).rising(), cfg["enrich"]["key_games_limit"])
        enrich.save_key_games(conn, key)
        if not (args.no_collect or args.no_enrich):
            enrich.run(conn, cfg, api, key, log=log)
        report.ensure_icons(conn, api, site.site_games(radar, extra=key), log=log)
        radar.games = waves.Radar(conn, cfg).games  # pick up icons
        ins = insights.Insights(radar, conn, cfg)
        ins.record_track()
        r = cfg["radar"]
        n_runs = conn.execute("SELECT COUNT(*) FROM runs WHERE status IN ('ok','partial')").fetchone()[0]
        warmed_up = n_runs >= r["alert_min_runs"] and len(radar.games) >= r["alert_min_games"] and not args.no_alerts
        found = (found + ins.forming(warmed_up))[:r["max_alerts_per_run"]]
        dashboard.write(radar, conn, cfg, log=log)
        site.write(radar, conn, cfg, ins, log=log)
        alerts.send(conn, radar, found, log=log)
        if args.vacuum:
            conn.execute("VACUUM")
        counts = {s: sum(1 for w in radar.waves if w["stage"] == s) for s in waves.STAGES}
        log(f"waves: {counts}; lone breakouts {len(radar.lone)}; done in {time.monotonic() - t0:.0f}s")


def cmd_report(args, conn, cfg):
    predict.grade(conn)
    path = report.write_reports(conn, cfg, None if args.offline else api_mod.Api(log=log), log=log)
    print(path)


def cmd_status(args, conn, cfg):
    runs = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (args.n,)).fetchall()
    print(f"database: {db.DB_PATH} ({db.DB_PATH.stat().st_size / 1e6:.1f} MB)" if db.DB_PATH.exists() else "no database yet")
    counts = conn.execute("SELECT (SELECT COUNT(*) FROM games), (SELECT COUNT(*) FROM snapshots),"
                          " (SELECT COUNT(*) FROM events WHERE baseline = 0)").fetchone()
    print(f"games {counts[0]:,} · snapshots {counts[1]:,} · real events {counts[2]:,}")
    for r in runs:
        print(f"  run {r['id']:>4}  {r['started_at']}  {r['status']:<8} refreshed {r['n_refreshed'] or 0:>6,}"
              f"  new {r['n_new_games'] or 0:>5,}  requests {r['requests'] or 0:>4}")
        if r["errors"]:
            for line in r["errors"].splitlines()[:5]:
                print(f"        ! {line[:150]}")


def cmd_find(args, conn, cfg):
    if args.online:
        api = api_mod.Api(log=log)
        for i, g in enumerate(api.search(args.text, 1)):
            if i >= args.n:
                break
            print(f"  {g['universeId']:>12}  {report.compact(g.get('playerCount')):>8}  {g.get('name')}")
        return
    rows = conn.execute(
        "SELECT universe_id, name, last_playing, peak_playing, created_at, genre_l1 FROM games "
        "WHERE name LIKE ? ORDER BY last_playing DESC LIMIT ?", (f"%{args.text}%", args.n)).fetchall()
    for r in rows:
        print(f"  {r['universe_id']:>12}  now {report.compact(r['last_playing']):>7}  peak {report.compact(r['peak_playing']):>7}"
              f"  {(r['created_at'] or '')[:10]}  {r['genre_l1'] or '':<11} {r['name']}")
    if not rows:
        print("no matches in the database (try --online)")


def cmd_game(args, conn, cfg):
    uid = resolve(conn, args.game)
    g = conn.execute("SELECT * FROM games WHERE universe_id = ?", (uid,)).fetchone()
    if not g:
        sys.exit(f"{uid} is not in the database yet (add it with: watch add {uid})")
    print(f"{g['name']}  (universe {uid}, place {g['root_place_id']})")
    print(f"  https://www.roblox.com/games/{g['root_place_id']}")
    print(f"  created {g['created_at']}  updated {g['updated_at']}  genre {g['genre_l1']}/{g['genre_l2']}")
    print(f"  creator {g['creator_name']} ({g['creator_type']})  max players {g['max_players']}")
    print(f"  first seen {g['first_seen_at']} via {g['first_seen_via']}")
    print(f"  playing now {g['last_playing']:,}  peak seen {g['peak_playing']:,} at {g['peak_playing_at']}"
          if g["last_playing"] is not None else "  no snapshots yet")
    names = conn.execute("SELECT name, first_seen_at FROM name_history WHERE universe_id = ? ORDER BY first_seen_at",
                         (uid,)).fetchall()
    if len(names) > 1:
        print("  names: " + " → ".join(n["name"] for n in names))
    print("  daily peak players:")
    for r in conn.execute("SELECT substr(ts,1,10) day, MAX(playing) p, MAX(visits) v FROM snapshots "
                          "WHERE universe_id = ? GROUP BY day ORDER BY day DESC LIMIT ?", (uid, args.days)):
        print(f"    {r['day']}  {report.compact(r['p']):>8}  visits {report.compact(r['v'])}")
    for e in conn.execute("SELECT * FROM events WHERE universe_id = ? ORDER BY ts", (uid,)):
        tag = " (baseline)" if e["baseline"] else ""
        print(f"  event {e['ts']}  {e['kind']} {e['value'] or ''} {e['detail']}{tag}")
    for l in conn.execute("SELECT * FROM labels WHERE universe_id = ? ORDER BY key", (uid,)):
        print(f"  label {l['key']} = {l['value']}" + (f"  ({l['note']})" if l["note"] else ""))
    if g["description"] and args.description:
        print("\n" + g["description"])


def cmd_watch(args, conn, cfg):
    if args.action == "list":
        for uid, w in sorted(config.watchlist(conn, cfg).items(), key=lambda x: (x[1]["kind"], x[0])):
            g = conn.execute("SELECT name, last_playing FROM games WHERE universe_id = ?", (uid,)).fetchone()
            print(f"  {w['kind']:<8} {uid:>12}  {report.compact(g['last_playing'] if g else None):>8}"
                  f"  {(g['name'] if g and g['name'] else '')}  {w['note']}")
        return
    uid = resolve(conn, args.game)
    if args.action == "add":
        conn.execute("INSERT OR REPLACE INTO watch VALUES (?,?,?,?)", (uid, args.kind, args.note, db.iso(db.now())))
        print(f"watching {uid} as '{args.kind}' (picked up on the next run)")
    else:
        conn.execute("DELETE FROM watch WHERE universe_id = ?", (uid,))
        print(f"removed {uid} from the command-line watchlist (config.toml entries stay until edited)")
    conn.commit()


def cmd_label(args, conn, cfg):
    if args.game == "list":
        q = "SELECT l.*, g.name FROM labels l LEFT JOIN games g USING (universe_id)"
        rows = conn.execute(q + (" WHERE key = ?" if args.pairs else "") + " ORDER BY key, value",
                            tuple(args.pairs[:1])).fetchall()
        for r in rows:
            print(f"  {r['key']:<24} {r['value']:<20} {r['name'] or r['universe_id']}")
        return
    uid = resolve(conn, args.game)
    for pair in args.pairs:
        if "=" not in pair:
            sys.exit(f"labels look like key=value (got '{pair}')")
        k, v = pair.split("=", 1)
        if v == "":
            conn.execute("DELETE FROM labels WHERE universe_id = ? AND key = ?", (uid, k))
        else:
            conn.execute("INSERT OR REPLACE INTO labels VALUES (?,?,?,?,?)", (uid, k, v, args.note, db.iso(db.now())))
    conn.commit()
    print(f"labels saved for {uid}")


def cmd_predict(args, conn, cfg):
    if args.action == "add":
        uid = resolve(conn, args.game) if args.game else None
        subject = args.subject or (conn.execute("SELECT name FROM games WHERE universe_id = ?", (uid,)).fetchone() or [str(uid)])[0]
        pid = predict.add(conn, subject, args.peak, args.prob, by=args.by, within_days=args.within_days,
                          universe_id=uid, note=args.note)
        print(f"prediction #{pid} saved: {subject}: peak >= {args.peak:,} "
              f"{'by ' + args.by if args.by else f'within {args.within_days} days of launch'}, p={args.prob:.0%}")
    elif args.action == "link":
        predict.link(conn, args.id, resolve(conn, args.game))
        print(f"prediction #{args.id} linked")
    elif args.action == "grade":
        print(f"graded {predict.grade(conn)}")
    else:
        for p in conn.execute("SELECT * FROM predictions ORDER BY id"):
            res = "open" if p["outcome"] is None else ("HIT" if p["outcome"] else "miss")
            when = p["by_date"] or f"{p['within_days']}d after launch"
            print(f"  #{p['id']:<3} {res:<5} p={p['probability']:.0%}  peak>={p['threshold']:,} by {when}"
                  f"  actual {p['actual_peak'] if p['actual_peak'] is not None else '—'}  {p['subject']}")
        sb = predict.scoreboard(conn)
        if sb["graded"]:
            print(f"  hit rate {sb['hits']}/{sb['graded']}, Brier {sb['brier']:.3f}")


def cmd_export(args, conn, cfg):
    cols = ["universe_id", "name", "creator_name", "created_at", "updated_at", "genre_l1", "genre_l2",
            "first_seen_at", "first_seen_via", "last_playing", "peak_playing", "peak_playing_at", "max_players"]
    rows = conn.execute(f"SELECT {', '.join(cols)} FROM games ORDER BY peak_playing DESC").fetchall()
    out = args.out or str(report.REPORTS / "games.csv")
    report.REPORTS.mkdir(exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows([tuple(r) for r in rows])
    print(f"wrote {len(rows):,} games to {out}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m tracker", description="Roblox trend tracker")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("radar", help="collect, find waves, write reports/DASHBOARD.md, send alerts (what GitHub runs)")
    s.add_argument("--no-collect", action="store_true", help="re-analyse the existing data only")
    s.add_argument("--no-alerts", action="store_true")
    s.add_argument("--no-enrich", action="store_true", help="skip the badge/creator lookups")
    s.add_argument("--vacuum", action="store_true", help="shrink the database file afterwards")
    s = sub.add_parser("run", help="collect, grade predictions, write the HTML report")
    s.add_argument("--no-report", action="store_true")
    s = sub.add_parser("report", help="rewrite the report from the database without collecting")
    s.add_argument("--offline", action="store_true", help="skip fetching missing icons")
    s = sub.add_parser("status", help="recent runs and database size")
    s.add_argument("-n", type=int, default=10)
    s = sub.add_parser("find", help="find games by name (database, or --online for Roblox search)")
    s.add_argument("text")
    s.add_argument("--online", action="store_true")
    s.add_argument("-n", type=int, default=15)
    s = sub.add_parser("game", help="everything known about one game")
    s.add_argument("game", help="universe id, place:<placeId>, or part of the name")
    s.add_argument("--days", type=int, default=21)
    s.add_argument("--description", action="store_true")
    s = sub.add_parser("watch", help="watch list: add / rm / list")
    s.add_argument("action", choices=["add", "rm", "list"])
    s.add_argument("game", nargs="?")
    s.add_argument("--kind", default="watch", help="mine | lineage | watch")
    s.add_argument("--note", default="")
    s = sub.add_parser("label", help="code a game for lineage analysis: label <game> stage.capability=treadmill ...; label list [key]")
    s.add_argument("game")
    s.add_argument("pairs", nargs="*")
    s.add_argument("--note")
    s = sub.add_parser("predict", help="prediction log: add / link / list / grade")
    s.add_argument("action", choices=["add", "link", "list", "grade"])
    s.add_argument("id", nargs="?", type=int, help="prediction id (for link)")
    s.add_argument("--game", help="universe id or name (leave out for an unpublished concept)")
    s.add_argument("--subject", help="concept or game name")
    s.add_argument("--peak", type=int, help="claim: peak players will reach at least this")
    s.add_argument("--by", help="deadline date, e.g. 2026-11-22")
    s.add_argument("--within-days", type=int, help="...or within N days of the game's creation")
    s.add_argument("--prob", type=float, help="your probability, 0-1, e.g. 0.3")
    s.add_argument("--note")
    s = sub.add_parser("export", help="write all games to a CSV")
    s.add_argument("--out")

    args = p.parse_args(argv)
    if args.cmd == "watch" and args.action != "list" and not args.game:
        p.error("watch add/rm needs a game")
    if args.cmd == "predict":
        if args.action == "add" and (args.peak is None or args.prob is None or not (args.game or args.subject)):
            p.error("predict add needs --peak, --prob and --game or --subject")
        if args.action == "link" and (args.id is None or not args.game):
            p.error("predict link <id> --game <game>")
    cfg = config.load()
    conn = db.connect()
    handler = globals()[f"cmd_{args.cmd}"]
    return handler(args, conn, cfg) or 0


if __name__ == "__main__":
    sys.exit(main())
