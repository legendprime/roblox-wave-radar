"""Builds reports/latest.md and reports/latest.html (plus a dated copy) from the database."""
import datetime as dt
import html
from pathlib import Path

from . import predict
from .api import ApiError
from .config import watchlist
from .db import ROOT, iso, now, parse_iso

REPORTS = ROOT / "reports"
BUCKETS = [(0, 100), (100, 1_000), (1_000, 10_000), (10_000, 100_000),
           (100_000, 1_000_000), (1_000_000, None)]


# ---- formatting ---------------------------------------------------------------

def compact(n):
    if n is None:
        return "—"
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1e6:.2f}M"
    if n >= 100_000:
        return f"{n / 1e3:.0f}K"
    if n >= 10_000:
        return f"{n / 1e3:.1f}K"
    return f"{n:,}"


def growth(cur, prev, have_prev):
    if not cur:
        return "—"
    if not have_prev:
        return "—"
    if not prev:
        return "new"
    return f"×{cur / prev:.1f}"


def days_since(s, ref):
    t = parse_iso(s)
    return None if t is None else (ref - t).total_seconds() / 86400


def fmt_days(d):
    if d is None:
        return "—"
    return f"{d * 24:.0f}h" if d < 2 else f"{d:.0f}d"


def bucket_label(lo, hi):
    return f"{compact(lo)}+" if hi is None else f"{compact(lo)}–{compact(hi)}"


class Game:
    """A table cell that renders as a linked game name (with icon in HTML)."""
    def __init__(self, uid):
        self.uid = uid


class Table:
    def __init__(self, title, intro, columns, rows, empty="Nothing yet."):
        self.title, self.intro, self.columns, self.rows, self.empty = title, intro, columns, rows, empty


# ---- data -------------------------------------------------------------------------

class Data:
    def __init__(self, conn, cfg):
        self.conn, self.cfg = conn, cfg
        self.t = now()
        self.run = conn.execute(
            "SELECT * FROM runs WHERE status IN ('ok','partial') ORDER BY id DESC LIMIT 1").fetchone()
        self.n_runs = conn.execute("SELECT COUNT(*) FROM runs WHERE status IN ('ok','partial')").fetchone()[0]
        self.first_ts = conn.execute("SELECT MIN(ts) FROM snapshots").fetchone()[0]
        self.games = {r["universe_id"]: r for r in conn.execute("SELECT * FROM games")}
        self.p24 = self.window(self.t - dt.timedelta(hours=24), self.t)
        self.prev24 = self.window(self.t - dt.timedelta(hours=48), self.t - dt.timedelta(hours=24))
        first = parse_iso(self.first_ts)
        self.have_prev = bool(first and first <= self.t - dt.timedelta(hours=30))
        self.latest = {}
        if self.run:
            self.latest = {r["universe_id"]: r for r in conn.execute(
                "SELECT * FROM snapshots WHERE run_id = ?", (self.run["id"],))}
        self.watch = watchlist(conn, cfg)

    def window(self, start, end):
        return {r[0]: r[1] for r in self.conn.execute(
            "SELECT universe_id, MAX(playing) FROM snapshots WHERE ts > ? AND ts <= ? GROUP BY universe_id",
            (iso(start), iso(end)))}

    def age(self, uid):
        g = self.games.get(uid)
        return days_since(g["created_at"], self.t) if g else None

    def likes(self, uid):
        s = self.latest.get(uid)
        if not s or not s["up_votes"]:
            return "—"
        total = (s["up_votes"] or 0) + (s["down_votes"] or 0)
        return f"{100 * s['up_votes'] / total:.0f}%" if total else "—"


# ---- sections ---------------------------------------------------------------------

def breakouts(d):
    r = d.cfg["report"]
    min_created = iso(d.t - dt.timedelta(days=r["breakout_max_age_days"]))
    rows = []
    for uid, g in d.games.items():
        p = d.p24.get(uid) or 0
        if g["created_at"] and g["created_at"] >= min_created and p >= r["breakout_min_peak"]:
            rows.append((uid, p, d.prev24.get(uid) or 0))
    key = (lambda x: x[1] - x[2]) if d.have_prev else (lambda x: x[1])
    rows.sort(key=key, reverse=True)
    out = []
    for uid, p, prev in rows[:30]:
        g = d.games[uid]
        out.append([Game(uid), fmt_days(d.age(uid)), compact(p),
                    compact(prev) if d.have_prev else "—", growth(p, prev, d.have_prev),
                    compact(g["peak_playing"]), g["genre_l1"] or "—", (g["first_seen_via"] or "")[:28]])
    intro = (f"Games created in the last {r['breakout_max_age_days']} days with at least "
             f"{r['breakout_min_peak']:,} players at some point in the last 24h, sorted by "
             + ("how much they grew since the day before." if d.have_prev else
                "players (growth columns fill in once there are two days of data)."))
    return Table("🚀 Breakouts: new games rising", intro,
                 ["Game", "Age", "Peak 24h", "Prev 24h", "Growth", "Peak seen", "Genre", "Found via"], out)


def milestones(d):
    since = iso(d.t - dt.timedelta(hours=24))
    rows = d.conn.execute(
        """SELECT * FROM events WHERE ts >= ? AND baseline = 0
           ORDER BY kind = 'crossed' DESC, value DESC, ts DESC LIMIT 60""", (since,)).fetchall()
    out = []
    for e in rows:
        if e["kind"] == "crossed":
            what = f"crossed {compact(e['value'])}" + (
                " (first seen above)" if e["detail"] == "first_seen_above" else "")
        else:
            what = f"entered {e['detail']}"
        out.append([Game(e["universe_id"]), what, fmt_days(d.age(e["universe_id"])),
                    compact((d.latest.get(e["universe_id"]) or {"playing": None})["playing"])])
    return Table("🏁 Milestones in the last 24 hours",
                 "First time a game passed a player threshold or appeared on a key chart. "
                 "The very first run's milestones are hidden (they were not new).",
                 ["Game", "Milestone", "Age", "Playing now"], out)


def genre_new(d):
    genres = set(d.cfg["report"]["lineage_genres"])
    min_created = iso(d.t - dt.timedelta(days=90))
    rows = [(uid, d.p24.get(uid) or 0) for uid, g in d.games.items()
            if g["genre_l1"] in genres and g["created_at"] and g["created_at"] >= min_created]
    rows.sort(key=lambda x: x[1], reverse=True)
    out = []
    for uid, p in rows[:40]:
        g = d.games[uid]
        out.append([Game(uid), fmt_days(d.age(uid)), compact(p),
                    growth(p, d.prev24.get(uid), d.have_prev), compact(g["peak_playing"]),
                    d.likes(uid), g["genre_l2"] or "—", fmt_days(days_since(g["updated_at"], d.t))])
    return Table(f"🥚 This genre: games under 90 days old ({', '.join(sorted(genres))})",
                 "The lineage's neighbourhood, by peak players in the last 24h.",
                 ["Game", "Age", "Peak 24h", "Growth", "Peak seen", "Likes", "Subgenre", "Last update"], out)


def watch_table(d, kind, title, intro):
    out = []
    items = [(uid, w) for uid, w in d.watch.items() if w["kind"] == kind]
    items.sort(key=lambda x: d.p24.get(x[0]) or 0, reverse=True)
    for uid, w in items:
        g = d.games.get(uid)
        s = d.latest.get(uid)
        out.append([Game(uid), w["note"], compact(s["playing"] if s else None), compact(d.p24.get(uid)),
                    growth(d.p24.get(uid), d.prev24.get(uid), d.have_prev),
                    compact(g["peak_playing"] if g else None), fmt_days(d.age(uid)),
                    fmt_days(days_since(g["updated_at"], d.t)) if g else "—",
                    compact(s["visits"] if s else None)])
    return Table(title, intro, ["Game", "Note", "Now", "Peak 24h", "Growth", "Peak seen",
                                "Age", "Last update", "Visits"], out, empty="No games on this list.")


def base_rates(d):
    genres = set(d.cfg["report"]["lineage_genres"])
    if not d.first_ts:
        return Table("📊 Base rates", "", [], [])
    cohort_start = iso(parse_iso(d.first_ts) - dt.timedelta(days=3))
    cohort = [g for g in d.games.values()
              if g["genre_l1"] in genres and g["created_at"] and g["created_at"] >= cohort_start]
    recent_start = iso(d.t - dt.timedelta(days=120))
    recent = [g for g in d.games.values()
              if g["genre_l1"] in genres and g["created_at"] and g["created_at"] >= recent_start]

    def count(games):
        res = []
        for lo, hi in BUCKETS:
            n = sum(1 for g in games if (g["peak_playing"] or 0) >= lo and (hi is None or (g["peak_playing"] or 0) < hi))
            res.append(n)
        return res

    c1, c2 = count(cohort), count(recent)
    rows = [[bucket_label(lo, hi), f"{a:,}", f"{b:,}"] for (lo, hi), a, b in zip(BUCKETS, c1, c2)]
    rows.append(["Total", f"{len(cohort):,}", f"{len(recent):,}"])
    tracked_days = (d.t - parse_iso(d.first_ts)).total_seconds() / 86400
    return Table(
        "📊 Base rates: how high do games in this genre get?",
        f"Highest player count each game reached while tracked, bucketed. Left column: games "
        f"created since tracking began ({tracked_days:.1f} days ago), so their whole life is "
        f"observed; this is the honest column and fills in over weeks. Right column: all genre "
        f"games created in the last 120 days, but older ones were already past their peak "
        f"when tracking started, so it understates them. Both only include games that showed "
        f"up in charts or search at least once.",
        ["Peak players", "Launched since tracking", "Created in last 120 days"], rows)


def predictions(d):
    sb = predict.scoreboard(d.conn)
    rows = d.conn.execute(
        "SELECT * FROM predictions ORDER BY outcome IS NOT NULL, id DESC LIMIT 40").fetchall()
    out = []
    for p in rows:
        when = (p["by_date"] or "")[:10] if p["by_date"] else f"{p['within_days']}d after launch"
        status = "open" if p["outcome"] is None else ("HIT" if p["outcome"] else "miss")
        subj = Game(p["universe_id"]) if p["universe_id"] else p["subject"]
        out.append([p["id"], subj, f"≥ {compact(p['threshold'])} by {when}", f"{p['probability']:.0%}",
                    compact(p["actual_peak"]), status])
    intro = f"{sb['graded']} graded, {sb['open']} open."
    if sb["graded"]:
        intro += (f" Hit rate {sb['hits'] / sb['graded']:.0%} vs average stated probability "
                  f"{sb['mean_prob']:.0%}; Brier score {sb['brier']:.3f} (0 is perfect, 0.25 is "
                  f"coin-flip guessing). By stated probability: "
                  + "; ".join(f"{b} → {n} predictions, {r:.0%} hit" for b, n, r in sb["buckets"]) + ".")
    else:
        intro += " Add one with: python3 -m tracker predict add --help"
    return Table("🎯 Prediction log", intro, ["#", "Subject", "Claim", "Said", "Actual peak", "Result"],
                 out, empty="No predictions yet.")


def top_overall(d):
    rows = sorted(d.latest.values(), key=lambda s: s["playing"] or 0, reverse=True)[:25]
    out = [[i, Game(s["universe_id"]), compact(s["playing"]),
            d.games[s["universe_id"]]["genre_l1"] or "—", fmt_days(d.age(s["universe_id"]))]
           for i, s in enumerate(rows, 1)]
    return Table("🏆 Top 25 right now", "All tracked games, by players at the last run.",
                 ["#", "Game", "Playing", "Genre", "Age"], out)


def build_tables(d):
    return [
        breakouts(d),
        milestones(d),
        watch_table(d, "mine", "🧑‍💻 Your games", "Your games from the watchlist."),
        genre_new(d),
        watch_table(d, "lineage", "🧬 Lineage reference games",
                    "The games from the lineage doc, plus flops kept for comparison. "
                    "Peaks in notes are historical; 'Peak seen' is only what this tracker observed."),
        base_rates(d),
        predictions(d),
        top_overall(d),
    ]


# ---- rendering --------------------------------------------------------------------

def game_url(g):
    return f"https://www.roblox.com/games/{g['root_place_id']}" if g and g["root_place_id"] else None


def md_cell(d, v):
    if isinstance(v, Game):
        g = d.games.get(v.uid)
        name = (g["name"] if g and g["name"] else str(v.uid))
        name = name.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]").replace("\n", " ")
        url = game_url(g)
        return f"[{name}]({url})" if url else name
    return str(v).replace("|", "\\|").replace("\n", " ")


def html_cell(d, v):
    if isinstance(v, Game):
        g = d.games.get(v.uid)
        name = html.escape(g["name"] if g and g["name"] else str(v.uid))
        icon = (f'<img src="{html.escape(g["icon_url"])}" alt="" loading="lazy">'
                if g and g["icon_url"] else '<span class="noicon"></span>')
        url = game_url(g)
        label = f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{name}</a>' if url else name
        return f'<td class="game">{icon}{label}</td>'
    s = html.escape(str(v))
    cls = ' class="num"' if s[:1].isdigit() or s[:1] in "×—" else ""
    return f"<td{cls}>{s}</td>"


def header_lines(d):
    run = d.run
    lines = [f"Generated {d.t.astimezone().strftime('%a %b %-d, %Y %-I:%M %p')} (local time)."]
    if run:
        lines.append(f"Last collection: {parse_iso(run['started_at']).astimezone().strftime('%b %-d %-I:%M %p')}, "
                     f"status {run['status']}, {run['n_refreshed']:,} games refreshed, "
                     f"{run['n_new_games']:,} new.")
    tracked = len(d.games)
    since = parse_iso(d.first_ts).astimezone().strftime('%b %-d, %Y') if d.first_ts else "—"
    lines.append(f"{tracked:,} games in the database from {d.n_runs} runs since {since}.")
    if not d.have_prev:
        lines.append("Less than two days of history so far: growth columns stay empty until then.")
    return lines


def render_md(d, tables):
    out = ["# Roblox Trend Tracker", ""] + [f"_{x}_  " for x in header_lines(d)] + [""]
    for t in tables:
        out += [f"## {t.title}", "", t.intro, ""]
        if not t.rows:
            out += [f"_{t.empty}_", ""]
            continue
        out.append("| " + " | ".join(t.columns) + " |")
        out.append("|" + "|".join("---" for _ in t.columns) + "|")
        for r in t.rows:
            out.append("| " + " | ".join(md_cell(d, v) for v in r) + " |")
        out.append("")
    return "\n".join(out)


CSS = """
:root{--bg:#fbfaf8;--fg:#1d1b18;--muted:#6b665e;--line:#e6e1d8;--card:#fff;--accent:#c2410c;--row:#f5f2ec}
@media (prefers-color-scheme: dark){:root{--bg:#141311;--fg:#ece8e1;--muted:#a39d93;--line:#2c2a26;--card:#1c1b18;--accent:#fb923c;--row:#22201c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:24px;margin:0 0 6px}h2{font-size:17px;margin:34px 0 4px}
.meta{color:var(--muted);margin:0}.intro{color:var(--muted);margin:2px 0 10px;max-width:880px}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}
table{border-collapse:collapse;width:100%;min-width:640px}
th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{font-weight:600;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.03em}
tr:last-child td{border-bottom:0}tbody tr:nth-child(even){background:var(--row)}
td.num{text-align:right;font-variant-numeric:tabular-nums}
td.game{display:flex;align-items:center;gap:8px;max-width:380px;white-space:normal}
td.game img,.noicon{width:28px;height:28px;border-radius:6px;flex:none;background:var(--line)}
a{color:var(--fg);text-decoration:none;border-bottom:1px solid var(--line)}a:hover{color:var(--accent);border-color:var(--accent)}
.empty{color:var(--muted);font-style:italic}
"""


def render_html(d, tables):
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             "<title>Roblox Trend Tracker</title>", f"<style>{CSS}</style></head><body><main>",
             "<h1>Roblox Trend Tracker</h1>"]
    parts += [f'<p class="meta">{html.escape(x)}</p>' for x in header_lines(d)]
    for t in tables:
        parts.append(f"<h2>{html.escape(t.title)}</h2><p class=\"intro\">{html.escape(t.intro)}</p>")
        if not t.rows:
            parts.append(f'<p class="empty">{html.escape(t.empty)}</p>')
            continue
        parts.append('<div class="wrap"><table><thead><tr>'
                     + "".join(f"<th>{html.escape(c)}</th>" for c in t.columns) + "</tr></thead><tbody>")
        for r in t.rows:
            parts.append("<tr>" + "".join(html_cell(d, v) for v in r) + "</tr>")
        parts.append("</tbody></table></div>")
    parts.append("</main></body></html>")
    return "\n".join(parts)


def ensure_icons(conn, api, uids, log=print):
    stale = iso(now() - dt.timedelta(days=7))
    need = [r[0] for r in conn.execute(
        "SELECT universe_id FROM games WHERE universe_id IN (%s) AND (icon_url IS NULL OR icon_fetched_at < ?)"
        % ",".join(str(int(u)) for u in uids), (stale,))] if uids else []
    if not need:
        return
    try:
        icons = api.icons(need)
    except ApiError as e:
        log(f"  ! icons: {e}")
        return
    ts = iso(now())
    conn.executemany("UPDATE games SET icon_url = ?, icon_fetched_at = ? WHERE universe_id = ?",
                     [(icons.get(u), ts, u) for u in need])
    conn.commit()


def write_reports(conn, cfg, api=None, log=print):
    d = Data(conn, cfg)
    tables = build_tables(d)
    if api is not None:
        uids = {v.uid for t in tables for r in t.rows for v in r if isinstance(v, Game)}
        ensure_icons(conn, api, sorted(uids), log)
        d.games = {r["universe_id"]: r for r in conn.execute("SELECT * FROM games")}
    md, page = render_md(d, tables), render_html(d, tables)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "daily").mkdir(exist_ok=True)
    day = d.t.astimezone().strftime("%Y-%m-%d")
    for path, text in [(REPORTS / "latest.md", md), (REPORTS / "latest.html", page),
                       (REPORTS / "daily" / f"{day}.md", md), (REPORTS / "daily" / f"{day}.html", page)]:
        Path(path).write_text(text, encoding="utf-8")
    log(f"report written: {REPORTS / 'latest.html'}")
    return REPORTS / "latest.html"
