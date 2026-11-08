"""Builds the radar website: site/index.html (everything inside one page) + site/waves.json.
GitHub Pages serves the site/ folder; see .github/workflows/radar.yml."""
import datetime as dt
import json
from zoneinfo import ZoneInfo

from .db import ROOT, iso

SITE = ROOT / "site"
SPARK_DAYS = 14


def _num(x, nd=3):
    return None if x is None else round(x, nd)


class SiteData:
    def __init__(self, radar, conn, cfg, insights):
        self.R, self.conn, self.cfg, self.I = radar, conn, cfg, insights
        self.days = [(radar.t - dt.timedelta(days=d)).strftime("%Y-%m-%d") for d in range(SPARK_DAYS - 1, -1, -1)]

    def game(self, uid, rich=False):
        R, I = self.R, self.I
        g = R.games.get(uid)
        icon = g["icon_url"] if g and g["icon_url"] and str(g["icon_url"]).startswith("https://tr.rbxcdn.com/") else None
        genre = " / ".join(x for x in ((g["genre_l1"], g["genre_l2"]) if g else ()) if x)
        p = I.proxies(uid)
        out = {"id": uid, "name": (g["name"] if g else None) or str(uid),
               "place": g["root_place_id"] if g else None, "icon": icon,
               "playing": R.playing(uid), "peak": (g["peak_playing"] if g else None),
               "age": _num(R.age(uid)), "genre": genre, "growth_24h": _num(R.growth([uid], 24)),
               "like": p.get("like"), "upd": p.get("last_update_days")}
        if rich:
            out.update({k: p.get(k) for k in ("visits_per_day", "minutes_per_visit", "favs_per_1k", "updates_14d",
                                              "badges", "creator")})
            out["mech"] = I.mechanics(uid)
        return out

    def spark(self, uids):
        if not uids:
            return []
        marks = ",".join(str(int(u)) for u in uids)
        rows = dict(self.conn.execute(
            f"SELECT day, SUM(peak_playing) FROM daily WHERE universe_id IN ({marks}) AND day >= ? GROUP BY day",
            (self.days[0],)).fetchall())
        return [{"day": d, "total": rows.get(d)} for d in self.days]

    def wave(self, w, members_limit, detailed):
        I = self.I
        everyone = set(w["members"]) | {w["leader"]}
        keys = ("key", "label", "stage", "why", "parent", "terms", "n", "n7", "n14", "hits", "hits10", "eligible",
                "recent", "recent_hits", "total", "genre", "lineage")
        out = {k: w.get(k) for k in keys}
        out.update({
            "hit_rate": _num(w["hit_rate"]), "recent_hit_rate": _num(w.get("recent_hit_rate")),
            "growth_24h": _num(w["growth_24h"]), "growth_72h": _num(w["growth_72h"]), "growth_7d": _num(w["growth_7d"]),
            "leader_age": _num(w["leader_age"]),
            "spark": self.spark(everyone),
            "leader": self.game(w["leader"], rich=True),
            "best": [self.game(u, rich=detailed) for u in w["best"]],
            "newest": [self.game(u) for u in w["newest"]],
            "members": [self.game(u) for u in w["members"][:members_limit]],
            "mechanics": I.wave_mechanics(w),
        })
        if detailed:
            out["wvf"] = I.winners_vs_flops(w)
            bs = I.big_share(everyone)
            out["big_share"] = _num(bs)
            if w["stage"] in ("jump", "starting"):
                out["score_why"] = I.wave_score(w)[1]
        return out

    def build(self):
        R, I, r = self.R, self.I, self.cfg["radar"]
        tz = ZoneInfo(r["timezone"])
        show = []
        for w in R.waves:
            if w["stage"] in ("jump", "starting", "fading"):
                show.append(self.wave(w, 80, detailed=True))
            elif w["stage"] == "crowded" and w["total"] >= r["show_crowded_min_total"] \
                    and (w["leader_age"] or 0) <= r["show_crowded_max_leader_age"]:
                show.append(self.wave(w, 30, detailed=True))
            elif w["stage"] == "watching" and w["n"] >= 5:
                show.append(self.wave(w, 20, detailed=False))
        lone = []
        for x in R.lone:
            g = self.game(x["uid"], rich=True)
            g.update({"lookalikes": x["n_copies"], "lookalike_games": [self.game(u) for u in x["copies"]]})
            lone.append(g)
        opps = []
        for o in I.opportunities():
            opps.append({k: o[k] for k in ("kind", "key", "label", "stage", "score", "why")}
                        | {"leader": self.game(o["leader"])})
        rising = [self.game(x["uid"]) | {"wave": x["wave"], "wave_stage": x["wave_stage"]} for x in I.rising()]
        charts = [self.game(x["uid"]) | {"chart": x["chart"], "position": x["position"]} for x in I.chart_entries()]
        mine = [self.game(x["uid"], rich=True) | {"note": x["note"], "wave": x["wave"], "wave_stage": x["wave_stage"]}
                for x in I.my_games()]
        mech = [{k: m[k] for k in ("name", "games", "eligible", "hits", "hit_rate", "new_this_week", "new_last_week")}
                | {"top": [self.game(u) for u in m["top"]]} for m in I.mechanic_trends()]
        srow = self.conn.execute("SELECT value FROM meta WHERE key = 'last_search'").fetchone()
        last = self.conn.execute(
            "SELECT errors FROM runs WHERE status IN ('ok','partial') ORDER BY id DESC LIMIT 1").fetchone()
        return {
            "updated": iso(R.t),
            "updated_label": R.t.astimezone(tz).strftime("%a %b %-d, %-I:%M %p %Z"),
            "history_hours": round(R.history_hours, 1),
            "games_tracked": self.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0],
            "search": json.loads(srow[0]) if srow and srow[0] else None,
            "incomplete": (last["errors"].splitlines()[0][:200] if last and last["errors"] else None),
            "rules": {k: r[k] for k in ("wave_window_days", "jump_min_hits", "jump_hit_rate", "jump_max_age_days",
                                         "starting_max_age_days", "starting_max_games", "crowded_games",
                                         "crowded_hit_rate", "crowded_age_days", "fading_7d")},
            "big_members": self.cfg["enrich"]["big_creator_members"],
            "opportunities": opps, "waves": show, "lone": lone, "rising": rising, "charts": charts,
            "mine": mine, "mechanics": mech, "track": I.track_record(), "timelines": I.timelines(),
        }


def write(radar, conn, cfg, insights, log=print):
    data = SiteData(radar, conn, cfg, insights).build()
    SITE.mkdir(exist_ok=True)
    blob = json.dumps(data, separators=(",", ":"), default=str)
    (SITE / "waves.json").write_text(blob, encoding="utf-8")
    safe = blob.replace("</", "<\\/")  # can't close the <script> tag early
    (SITE / "index.html").write_text(PAGE.replace("/*DATA*/null", safe), encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    log(f"website written: {SITE / 'index.html'} ({len(blob) / 1024:.0f} KB of data)")
    return SITE / "index.html"


def site_games(radar, extra=()):
    """Every game the website shows, so their icons can be fetched."""
    uids = set(extra)
    for w in radar.waves:
        if w["stage"] in ("jump", "starting", "fading"):
            uids |= set(w["members"][:80]) | {w["leader"]}
        elif w["stage"] in ("crowded", "watching"):
            uids |= set(w["members"][:12]) | {w["leader"]}
    for x in radar.lone:
        uids |= {x["uid"], *x["copies"]}
    return sorted(uids)


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Roblox Wave Radar</title>
<meta name="description" content="Which Roblox game waves are open to jump into right now.">
<style>
:root{
  --bg:#f7f6f3;--panel:#ffffff;--ink:#1c1b19;--muted:#6d6a64;--line:#e5e2dc;--soft:#f0eee9;
  --jump:#15803d;--jump-bg:#e8f5ec;--start:#a16207;--start-bg:#fbf3e2;--crowd:#b91c1c;--crowd-bg:#fbeaea;
  --fade:#52525b;--fade-bg:#efeff1;--watch:#4b5563;--watch-bg:#f1f2f4;--lone:#6d28d9;--lone-bg:#f1ebfd;
  --accent:#2563eb;--spark:#2563eb;--bar:#2563eb;--shadow:0 1px 2px rgba(0,0,0,.05),0 2px 8px rgba(0,0,0,.04);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#121212;--panel:#1b1b1d;--ink:#ecebe8;--muted:#a3a19c;--line:#2c2c30;--soft:#232326;
    --jump:#4ade80;--jump-bg:#13291b;--start:#fbbf24;--start-bg:#2b2310;--crowd:#f87171;--crowd-bg:#2e1515;
    --fade:#a1a1aa;--fade-bg:#232326;--watch:#9ca3af;--watch-bg:#232326;--lone:#c4b5fd;--lone-bg:#231b38;
    --accent:#60a5fa;--spark:#60a5fa;--bar:#60a5fa;--shadow:none;
  }
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
a{color:inherit;text-decoration:none}
a:hover{color:var(--accent)}
main{max-width:1160px;margin:0 auto;padding:20px 16px 72px}
header h1{font-size:26px;line-height:1.2;margin:0 0 4px;letter-spacing:-.01em}
h2.sec{font-size:18px;margin:26px 0 10px}
.meta{color:var(--muted);font-size:13.5px;margin:0}
.notes{margin:12px 0 0;display:grid;gap:6px}
.note{background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:8px 12px;font-size:13.5px;color:var(--muted)}
.note.warn{border-color:var(--start);color:var(--ink)}
.opps{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.opp{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px;box-shadow:var(--shadow);cursor:pointer;
  display:flex;gap:12px;align-items:flex-start;min-width:0;text-align:left;font:inherit;color:inherit;width:100%}
.opp:hover{border-color:var(--accent)}
.opp .rank{font-size:22px;font-weight:700;color:var(--muted);width:22px;flex:none;line-height:1.2}
.opp img,.opp .ph{width:44px;height:44px;border-radius:10px;flex:none;background:var(--line);object-fit:cover}
.opp .name{font-weight:650;word-break:break-word;line-height:1.3}
.opp .why{font-size:13px;color:var(--muted);margin-top:4px}
.scorebar{height:5px;background:var(--soft);border-radius:4px;margin-top:8px;overflow:hidden}
.scorebar span{display:block;height:100%;background:var(--bar);border-radius:4px}
.mine{display:flex;flex-wrap:wrap;gap:8px}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:22px 0 12px}
.tab{appearance:none;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:999px;
  padding:7px 14px;font:inherit;font-size:14px;cursor:pointer;display:inline-flex;gap:6px;align-items:center}
.tab[aria-pressed="true"]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.tab .n{font-variant-numeric:tabular-nums;opacity:.75}
.controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:18px}
.controls input[type=search]{flex:1 1 220px;min-width:0;border:1px solid var(--line);background:var(--panel);color:var(--ink);
  border-radius:10px;padding:9px 12px;font:inherit}
.controls label{display:inline-flex;gap:6px;align-items:center;font-size:14px;color:var(--muted);cursor:pointer}
.section-intro{color:var(--muted);margin:0 0 14px;max-width:860px}
.grid{display:grid;gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:var(--shadow);min-width:0}
.card-top{display:flex;gap:12px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}
.card h3{font-size:21px;margin:0;line-height:1.25;word-break:break-word}
.badge{display:inline-block;font-size:12.5px;font-weight:600;border-radius:999px;padding:3px 10px;white-space:nowrap}
.b-jump{color:var(--jump);background:var(--jump-bg)}.b-starting{color:var(--start);background:var(--start-bg)}
.b-crowded{color:var(--crowd);background:var(--crowd-bg)}.b-fading{color:var(--fade);background:var(--fade-bg)}
.b-watching{color:var(--watch);background:var(--watch-bg)}.b-lone{color:var(--lone);background:var(--lone-bg)}
.b-none{color:var(--muted);background:var(--soft)}
.pocket{font-size:13px;color:var(--muted);margin:6px 0 0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:14px 0 10px}
.stat{background:var(--soft);border-radius:10px;padding:8px 10px;min-width:0}
.stat .v{font-size:19px;font-weight:650;font-variant-numeric:tabular-nums;line-height:1.2}
.stat .k{font-size:12px;color:var(--muted)}
.why{font-size:13.5px;color:var(--muted);margin:2px 0 12px}
.spark{display:flex;align-items:flex-end;gap:10px;margin:0 0 12px}
.spark svg{width:100%;max-width:340px;height:56px;display:block}
.cap{font-size:12px;color:var(--muted);white-space:nowrap}
.row{display:flex;gap:10px;align-items:center;min-width:0}
.label{font-size:12.5px;color:var(--muted);margin:12px 0 6px;font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.leader{display:flex;gap:12px;align-items:center;background:var(--soft);border-radius:12px;padding:10px;min-width:0}
.leader img,.leader .ph{width:48px;height:48px;border-radius:10px;flex:none;background:var(--line);object-fit:cover}
.leader .name{font-weight:600;word-break:break-word}
.sub{font-size:13px;color:var(--muted)}
.facts{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.fact{font-size:12.5px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:2px 8px;color:var(--ink)}
.fact b{font-weight:650}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{display:inline-flex;gap:8px;align-items:center;border:1px solid var(--line);border-radius:10px;padding:5px 9px 5px 5px;
  max-width:100%;min-width:0;background:var(--panel)}
.chip img,.chip .ph{width:26px;height:26px;border-radius:6px;flex:none;background:var(--line);object-fit:cover}
.chip .t{font-size:13.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:220px}
.chip .s{font-size:12.5px;color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums}
.tag{display:inline-block;font-size:12.5px;border-radius:999px;padding:2px 9px;background:var(--soft);border:1px solid var(--line)}
.tags{display:flex;flex-wrap:wrap;gap:6px}
.box{background:var(--soft);border-radius:12px;padding:10px 12px;margin-top:10px;font-size:13.5px}
.box p{margin:2px 0}
.more{appearance:none;border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:10px;padding:7px 12px;
  font:inherit;font-size:13.5px;cursor:pointer;margin-top:12px}
.tablewrap{overflow-x:auto;margin-top:10px;border:1px solid var(--line);border-radius:10px;background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap;vertical-align:middle}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em;background:var(--soft)}
tr:last-child td{border-bottom:0}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
td.g{white-space:normal;min-width:190px}
td.g .row img,td.g .row .ph{width:24px;height:24px;border-radius:6px;flex:none;background:var(--line)}
td.wrap{white-space:normal;min-width:200px}
.hbar{display:inline-block;width:70px;height:6px;background:var(--soft);border-radius:4px;vertical-align:middle;margin-left:6px;overflow:hidden}
.hbar span{display:block;height:100%;background:var(--bar)}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.tile{display:flex;gap:12px;align-items:flex-start;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px;min-width:0}
.tile img,.tile .ph{width:64px;height:64px;border-radius:12px;flex:none;background:var(--line);object-fit:cover}
.tile .name{font-weight:600;word-break:break-word;line-height:1.3}
.strip{display:flex;gap:3px;flex-wrap:wrap}
.strip span{width:14px;height:14px;border-radius:3px;display:inline-block}
.s-jump{background:var(--jump)}.s-starting{background:var(--start)}.s-crowded{background:var(--crowd)}
.s-fading{background:var(--fade)}.s-watching{background:var(--line)}
.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);margin:6px 0 12px}
.legend i{width:12px;height:12px;border-radius:3px;display:inline-block;vertical-align:-1px;margin-right:4px}
.empty{color:var(--muted);font-style:italic;padding:12px 0}
footer{margin-top:40px;color:var(--muted);font-size:13.5px;border-top:1px solid var(--line);padding-top:18px}
footer h3{color:var(--ink);font-size:15px;margin:14px 0 8px}
footer ul{margin:0 0 12px;padding-left:18px}
@media (max-width:560px){ header h1{font-size:22px} .card h3{font-size:19px} .chip .t{max-width:150px} .opps{grid-template-columns:1fr} }
</style>
</head>
<body>
<main>
  <header>
    <h1>📡 Roblox Wave Radar</h1>
    <p class="meta" id="meta"></p>
    <div class="notes" id="notes"></div>
  </header>
  <h2 class="sec">⭐ Top opportunities right now</h2>
  <div class="opps" id="opps"></div>
  <h2 class="sec" id="mine-h">🧑‍💻 Your games</h2>
  <div class="mine" id="mine"></div>
  <nav class="tabs" id="tabs" aria-label="Sections"></nav>
  <div class="controls" id="controls">
    <input type="search" id="q" placeholder="Find a wave or a game…" aria-label="Find a wave or a game">
    <label><input type="checkbox" id="lineage"> Tycoon lineage only</label>
  </div>
  <p class="section-intro" id="intro"></p>
  <section id="list" class="grid" aria-live="polite"></section>
  <footer id="foot"></footer>
</main>
<script id="data" type="application/json">/*DATA*/null</script>
<script>
(function(){
"use strict";
var D = JSON.parse(document.getElementById("data").textContent) || {};
["opportunities","waves","lone","rising","charts","mine","mechanics","timelines"].forEach(function(k){ D[k] = D[k] || []; });
D.track = D.track || {stages:[]};
var TABS = [
  {id:"jump", name:"Jump in now", emoji:"🟢", intro:"Copies with a twist are succeeding and it isn't crowded yet. This is the window, and it lasts weeks, not months."},
  {id:"starting", name:"Just starting", emoji:"🌱", intro:"A young game is breaking out and only a few copies exist. If the copies start succeeding, it moves to Jump in now."},
  {id:"lone", name:"Lone breakouts", emoji:"👀", intro:"Young games pulling big numbers with no wave around them yet. The next wave usually starts as one of these. 🌊 marks one that just got its first lookalikes."},
  {id:"rising", name:"Rising fastest", emoji:"🚀", intro:"Young games (under 45 days, 1K+ players) growing fastest over the last 24 hours. Needs a day of history."},
  {id:"charts", name:"New on charts", emoji:"📈", intro:"Games that showed up on Up-and-Coming, Top Trending, Trending in Simulation or Top Playing Now for the first time in the last 24 hours: the earliest public sign of a breakout."},
  {id:"crowded", name:"Crowded", emoji:"🔴", intro:"The wave is real but the window has closed: copies mostly fail, or the leader is old. Only a big change (new theme plus a reworked loop) has a shot."},
  {id:"fading", name:"Fading", emoji:"⚫", intro:"Total players are falling."},
  {id:"watching", name:"Watching", emoji:"·", intro:"Groups that don't meet any stage yet."},
  {id:"mechanics", name:"Mechanics", emoji:"🧩", intro:"Game mechanics found in the titles and descriptions of games made in the last 60 days: how often games with each one reach 1K players, and whether more are being made this week than last. Rough: detected from keywords."},
  {id:"track", name:"Track record", emoji:"🎯", intro:"Does the radar work? For every copy made since tracking began, it records what stage its wave was in on the day it was made, then whether it reached 1K players within 14 days."}
];
var STAGE_NAMES = {jump:"🟢 Jump in now", starting:"🌱 Just starting", crowded:"🔴 Crowded", fading:"⚫ Fading", watching:"· Watching", lone:"👀 Lone breakout"};

function h(tag, attrs){
  var el = document.createElement(tag);
  if (attrs) for (var k in attrs){
    if (attrs[k] == null || attrs[k] === false) continue;
    if (k === "text") el.textContent = attrs[k];
    else if (k === "cls") el.className = attrs[k];
    else if (k === "on") for (var ev in attrs.on) el.addEventListener(ev, attrs.on[ev]);
    else el.setAttribute(k, attrs[k]);
  }
  for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
  return el;
}
function add(el, c){
  if (c == null || c === false) return;
  if (Array.isArray(c)) { c.forEach(function(x){ add(el, x); }); return; }
  el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
}
function fmt(n){
  if (n == null) return "—";
  if (n >= 1e9) return (n/1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n/1e6).toFixed(n >= 1e8 ? 0 : 2) + "M";
  if (n >= 1e5) return Math.round(n/1e3) + "K";
  if (n >= 1e4) return (n/1e3).toFixed(1) + "K";
  return Math.round(n).toLocaleString();
}
function days(d){ if (d == null) return "—"; return d < 2 ? Math.round(d*24) + "h" : Math.round(d) + "d"; }
function pct(x){ return x == null ? "—" : Math.round(x*100) + "%"; }
function trend(g){ if (g == null) return "—"; var p = Math.round((g-1)*100); return (p >= 0 ? "+" : "") + p + "%"; }
function url(g){ return g && /^\d+$/.test(String(g.place || "")) ? "https://www.roblox.com/games/" + g.place : null; }
function icon(g, cls){ return g && g.icon ? h("img", {src:g.icon, alt:"", loading:"lazy", referrerpolicy:"no-referrer", cls:cls}) : h("span", {cls:"ph " + (cls||"")}); }
function link(g, child){ var u = url(g); return u ? h("a", {href:u, target:"_blank", rel:"noopener"}, child) : child; }
function badge(stage){ return h("span", {cls:"badge b-" + (stage || "none"), text:STAGE_NAMES[stage] || "Not in a wave"}); }
function hbar(x){ return h("span", {cls:"hbar"}, h("span", {style:"width:" + Math.round(Math.max(0, Math.min(1, x || 0))*100) + "%"})); }

function facts(g){
  var f = [];
  var b = g.badges;
  if (b && b.visits_per_player) f.push(["visits per player", b.visits_per_player + "×", "Visits divided by the players who got its most common badge (“" + b.entry_badge + "”). Higher means players keep coming back."]);
  if (g.minutes_per_visit) f.push(["min per visit", String(g.minutes_per_visit), "Average players online × 1,440 ÷ visits per day. High can mean sticky or AFK-heavy."]);
  if (g.visits_per_day) f.push(["visits/day", fmt(g.visits_per_day)]);
  if (g.like != null) f.push(["liked", g.like + "%"]);
  if (g.favs_per_1k != null) f.push(["favorites per 1K visits", String(g.favs_per_1k)]);
  if (g.upd != null) f.push(["last update", days(g.upd) + " ago"]);
  if (g.updates_14d) f.push(["updates in 2 weeks", String(g.updates_14d)]);
  if (g.creator) f.push([g.creator.big ? "big studio" : "creator", (g.creator.name ? g.creator.name + " · " : "") +
    (g.creator.members ? fmt(g.creator.members) + (g.creator.type === "Group" ? " members" : " followers") : "") +
    (g.creator.n_games ? " · " + g.creator.n_games + " games" : ""), g.creator.top_game ? "Their biggest game: " + g.creator.top_game + " (" + fmt(g.creator.top_visits) + " visits)" : null]);
  if (!f.length) return null;
  return h("div", {cls:"facts"}, f.map(function(x){ return h("span", {cls:"fact", title:x[2] || null}, h("b", {text:x[1]}), " " + x[0]); }));
}
function badgeBits(g){
  var b = g.badges; if (!b) return null;
  var parts = [];
  if (b.milestones && b.milestones.length) parts.push(h("p", null, h("b", {text:"Progress: "}), b.milestones.map(function(m){ return m.name + " " + pct(m.share); }).join(" · ")));
  if (b.events && b.events.length) parts.push(h("p", null, h("b", {text:"New in the last 3 weeks: "}), b.events.map(function(m){ return m.name + " (" + fmt(m.awarded) + " players)"; }).join(" · ")));
  return parts.length ? h("div", {cls:"box"}, parts) : null;
}

function spark(points){
  var vals = (points || []).map(function(p){ return p.total; });
  var have = vals.filter(function(v){ return v != null; });
  if (have.length < 2) return h("div", {cls:"spark"}, h("span", {cls:"cap", text:"Player chart appears after 2 days of history"}));
  var max = Math.max.apply(null, have), min = Math.min.apply(null, have), W = 340, H = 56, pad = 4;
  var step = (W - pad*2) / (vals.length - 1), pts = [];
  vals.forEach(function(v, i){ if (v == null) return; var y = max === min ? H/2 : pad + (H - pad*2) * (1 - (v-min)/(max-min)); pts.push([pad + i*step, y]); });
  var ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 " + W + " " + H); svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Players in this wave, last " + vals.length + " days");
  var area = document.createElementNS(ns, "path");
  area.setAttribute("d", "M" + pts[0][0] + "," + H + " L" + pts.map(function(p){ return p[0] + "," + p[1]; }).join(" L") + " L" + pts[pts.length-1][0] + "," + H + " Z");
  area.setAttribute("fill", "var(--spark)"); area.setAttribute("opacity", "0.12"); svg.appendChild(area);
  var line = document.createElementNS(ns, "polyline");
  line.setAttribute("points", pts.map(function(p){ return p.join(","); }).join(" "));
  line.setAttribute("fill", "none"); line.setAttribute("stroke", "var(--spark)"); line.setAttribute("stroke-width", "2");
  line.setAttribute("stroke-linejoin", "round"); line.setAttribute("stroke-linecap", "round"); svg.appendChild(line);
  return h("div", {cls:"spark"}, svg, h("span", {cls:"cap", text:"players, " + vals.length + " days"}));
}
function chip(g){
  return link(g, h("span", {cls:"chip", title:g.name}, icon(g), h("span", {cls:"t", text:g.name}),
    h("span", {cls:"s", text:fmt(g.playing) + " · " + days(g.age)})));
}
function gameCell(g){ return h("td", {cls:"g"}, link(g, h("span", {cls:"row"}, icon(g), h("span", {text:g.name})))); }
function table(cols, rows){
  return h("div", {cls:"tablewrap"}, h("table", null,
    h("thead", null, h("tr", null, cols.map(function(c){ return h("th", {cls:c.num ? "num" : null, text:c.t}); }))),
    h("tbody", null, rows)));
}
function gamesTable(list){
  return table([{t:"Game"},{t:"Age",num:1},{t:"Playing",num:1},{t:"Peak seen",num:1},{t:"24h",num:1},{t:"Liked",num:1},{t:"Last update",num:1},{t:"Genre"}],
    list.map(function(g){
      return h("tr", null, gameCell(g), h("td", {cls:"num", text:days(g.age)}), h("td", {cls:"num", text:fmt(g.playing)}),
        h("td", {cls:"num", text:fmt(g.peak)}), h("td", {cls:"num", text:trend(g.growth_24h)}),
        h("td", {cls:"num", text:g.like != null ? g.like + "%" : "—"}), h("td", {cls:"num", text:g.upd != null ? days(g.upd) + " ago" : "—"}),
        h("td", {text:g.genre || "—"}));
    }));
}

function wvfBox(v){
  if (!v) return null;
  var lines = [h("p", null, h("b", {text:"Copies that reached 1K+ (" + v.winners + ") vs the rest (" + v.flops + "):"}))];
  var bits = [];
  if (v.like_w != null && v.like_f != null) bits.push("liked " + Math.round(v.like_w) + "% vs " + Math.round(v.like_f) + "%");
  bits.push("updated in the last week " + pct(v.updated_w) + " vs " + pct(v.updated_f));
  lines.push(h("p", {text:bits.join(" · ")}));
  if (v.more_in_winners.length) lines.push(h("p", {text:"Winners more often have: " + v.more_in_winners.join(", ")}));
  if (v.more_in_flops.length) lines.push(h("p", {text:"Flops more often have: " + v.more_in_flops.join(", ")}));
  return h("div", {cls:"box"}, lines);
}

function waveCard(w){
  var stats = h("div", {cls:"stats"},
    h("div", {cls:"stat"}, h("div", {cls:"v", text:(w.eligible ? w.hits + "/" + w.eligible : "—")}), h("div", {cls:"k", text:"copies reached 1K+ (" + pct(w.hit_rate) + ")"})),
    h("div", {cls:"stat"}, h("div", {cls:"v", text:(w.recent ? w.recent_hits + "/" + w.recent : "—")}), h("div", {cls:"k", text:"newest copies at 1K+"})),
    h("div", {cls:"stat"}, h("div", {cls:"v", text:String(w.n)}), h("div", {cls:"k", text:w.n7 + " new this week, " + w.n14 + " in 2 weeks"})),
    h("div", {cls:"stat"}, h("div", {cls:"v", text:fmt(w.total)}), h("div", {cls:"k", text:"playing now · 3-day " + trend(w.growth_72h)})),
    h("div", {cls:"stat"}, h("div", {cls:"v", text:days(w.leader_age)}), h("div", {cls:"k", text:"leader's age"})),
    w.big_share != null ? h("div", {cls:"stat"}, h("div", {cls:"v", text:pct(w.big_share)}), h("div", {cls:"k", text:"players in big-studio games"})) : null);
  var L = w.leader;
  var body = [
    h("div", {cls:"card-top"}, h("div", null, h("h3", {text:w.label}),
      w.parent ? h("p", {cls:"pocket", text:"A hot pocket inside the bigger “" + w.parent + "” wave, which is past its window."}) : null),
      badge(w.stage)),
    stats,
    h("p", {cls:"why", text:"Why: " + w.why + (w.lineage ? " · in the tycoon lineage" : " · " + (w.genre || "") + " (a part to borrow)")}),
    spark(w.spark),
    w.mechanics && w.mechanics.length ? h("div", null, h("div", {cls:"label", text:"Mechanics in this wave"}),
      h("div", {cls:"tags"}, w.mechanics.map(function(m){ return h("span", {cls:"tag", text:m.name + " " + pct(m.share)}); }))) : null,
    h("div", {cls:"label", text:"Leader"}),
    h("div", {cls:"leader"}, link(L, icon(L)), h("div", {style:"min-width:0"}, link(L, h("div", {cls:"name", text:L.name})),
      h("div", {cls:"sub", text:fmt(L.playing) + " playing · " + days(L.age) + " old · 24h " + trend(L.growth_24h)}), facts(L))),
    badgeBits(L),
    wvfBox(w.wvf)
  ];
  if (w.best && w.best.length) body.push(h("div", {cls:"label", text:"Doing best after it"}), h("div", {cls:"chips"}, w.best.map(chip)));
  if (w.newest && w.newest.length) body.push(h("div", {cls:"label", text:"Newest copies (this week)"}), h("div", {cls:"chips"}, w.newest.map(chip)));
  var others = (w.terms || []).filter(function(t){ return t !== w.label; });
  if (others.length) body.push(h("p", {cls:"sub", style:"margin:10px 0 0", text:"Other title words in this wave: " + others.slice(0, 8).join(", ")}));
  var card = h("article", {cls:"card", id:"w-" + w.key}, body);
  if (w.members && w.members.length){
    var holder = h("div");
    var btn = h("button", {cls:"more", type:"button", "aria-expanded":"false", text:"Show all " + w.members.length + " games"});
    btn.addEventListener("click", function(){
      var open = btn.getAttribute("aria-expanded") === "true";
      holder.textContent = "";
      if (!open) holder.appendChild(gamesTable(w.members));
      btn.setAttribute("aria-expanded", String(!open));
      btn.textContent = open ? "Show all " + w.members.length + " games" : "Hide games";
    });
    card.appendChild(btn); card.appendChild(holder);
  }
  return card;
}

function loneTile(g){
  var mech = (g.mech || []).slice(0, 3);
  return h("div", {cls:"tile"}, link(g, icon(g)), h("div", {style:"min-width:0"},
    link(g, h("div", {cls:"name", text:(g.lookalikes >= 2 ? "🌊 " : "") + g.name})),
    h("div", {cls:"sub", text:fmt(g.playing) + " playing · " + days(g.age) + " old" + (g.growth_24h != null ? " · 24h " + trend(g.growth_24h) : "")}),
    h("div", {cls:"sub", text:g.lookalikes ? g.lookalikes + " lookalike" + (g.lookalikes > 1 ? "s" : "") + " so far" + (g.lookalike_games && g.lookalike_games.length ? ": " + g.lookalike_games.map(function(x){ return x.name; }).slice(0, 2).join(", ") : "") : "No lookalikes yet"}),
    h("div", {cls:"sub", text:g.genre || ""}),
    mech.length ? h("div", {cls:"tags", style:"margin-top:6px"}, mech.map(function(m){ return h("span", {cls:"tag", text:m}); })) : null,
    facts(g)));
}

var state = {tab:"jump", q:"", lineage:false};
function waveMatches(w){
  if (state.lineage && !w.lineage) return false;
  var q = state.q; if (!q) return true;
  if (w.label.toLowerCase().indexOf(q) >= 0) return true;
  if ((w.terms || []).some(function(t){ return t.toLowerCase().indexOf(q) >= 0; })) return true;
  return (w.members || []).some(function(g){ return g.name.toLowerCase().indexOf(q) >= 0; });
}
function gameMatches(g){
  if (state.lineage && !/Tycoon|Incremental|Idle/.test(g.genre || "")) return false;
  return !state.q || g.name.toLowerCase().indexOf(state.q) >= 0;
}
function count(id){
  if (id === "lone") return D.lone.filter(gameMatches).length;
  if (id === "rising") return D.rising.filter(gameMatches).length;
  if (id === "charts") return D.charts.filter(gameMatches).length;
  if (id === "mechanics") return D.mechanics.length;
  if (id === "track") return (D.track.stages || []).reduce(function(a, s){ return a + s.launched; }, 0);
  return D.waves.filter(function(w){ return w.stage === id && waveMatches(w); }).length;
}
function go(tab, anchor){
  state.tab = tab; history.replaceState(null, "", "#" + tab); render();
  var el = anchor && document.getElementById(anchor);
  var tabs = document.getElementById("tabs");
  (el || tabs).scrollIntoView({behavior:"smooth", block:"start"});
}
function renderTabs(){
  var nav = document.getElementById("tabs"); nav.textContent = "";
  TABS.forEach(function(s){
    if ((s.id === "fading" || s.id === "watching") && !D.waves.some(function(w){ return w.stage === s.id; })) return;
    nav.appendChild(h("button", {cls:"tab", type:"button", "aria-pressed":String(state.tab === s.id),
      on:{click:function(){ go(s.id); }}}, s.emoji + " " + s.name, h("span", {cls:"n", text:String(count(s.id))})));
  });
}

function renderTrack(list){
  var T = D.track, st = T.stages || [];
  var since = T.since ? T.since.slice(0, 10) : "—", first = T.first_results ? T.first_results.slice(0, 10) : "—";
  list.appendChild(h("p", {cls:"note", text:"Collecting since " + since + ". Copies need " + (T.window_days || 14) + " days to finish, so the first finished results arrive around " + first + ". Until then, “so far” columns show early progress."}));
  if (!st.length) list.appendChild(h("p", {cls:"empty", text:"No copies recorded yet."}));
  else list.appendChild(table([{t:"Wave's stage on the copy's launch day"},{t:"Copies",num:1},{t:"Finished 14 days",num:1},{t:"Reached 1K",num:1},{t:"Reached 10K",num:1},{t:"Still running",num:1},{t:"At 1K so far",num:1}],
    st.map(function(s){
      return h("tr", null, h("td", null, s.stage in STAGE_NAMES ? badge(s.stage) : h("span", {cls:"badge b-none", text:s.stage})),
        h("td", {cls:"num", text:String(s.launched)}), h("td", {cls:"num", text:String(s.finished)}),
        h("td", {cls:"num", text:s.finished ? pct(s.hit1k / s.finished) : "—"}), h("td", {cls:"num", text:s.finished ? pct(s.hit10k / s.finished) : "—"}),
        h("td", {cls:"num", text:String(s.running)}), h("td", {cls:"num", text:s.running ? pct(s.running_hit1k / s.running) : "—"}));
    })));
  list.appendChild(h("h2", {cls:"sec", text:"Wave timelines (last 3 weeks)"}));
  list.appendChild(h("div", {cls:"legend"}, ["jump","starting","crowded","fading","watching"].map(function(s){ return h("span", null, h("i", {cls:"s-" + s}), STAGE_NAMES[s].replace(/^\S+\s/, "")); })));
  if (!D.timelines.length) { list.appendChild(h("p", {cls:"empty", text:"Timelines fill in day by day."})); return; }
  list.appendChild(table([{t:"Wave"},{t:"Stage by day"},{t:"Days open",num:1},{t:"First seen"}], D.timelines.map(function(w){
    return h("tr", null, h("td", {text:w.label}), h("td", null, h("div", {cls:"strip"}, w.days.map(function(d){ return h("span", {cls:"s-" + d.stage, title:d.day + ": " + (STAGE_NAMES[d.stage] || d.stage)}); }))),
      h("td", {cls:"num", text:String(w.jump_days)}), h("td", {text:w.first_day}));
  })));
}

function render(){
  renderTabs();
  var s = TABS.find(function(x){ return x.id === state.tab; }) || TABS[0];
  document.getElementById("intro").textContent = s.intro;
  var list = document.getElementById("list"); list.textContent = "";
  if (state.tab === "lone"){
    var lone = D.lone.filter(gameMatches);
    list.appendChild(lone.length ? h("div", {cls:"tiles"}, lone.map(loneTile)) : h("p", {cls:"empty", text:"Nothing here right now."}));
  } else if (state.tab === "rising"){
    var rs = D.rising.filter(gameMatches);
    list.appendChild(rs.length ? table([{t:"Game"},{t:"Age",num:1},{t:"Playing",num:1},{t:"24h",num:1},{t:"Wave"}], rs.map(function(g){
      return h("tr", null, gameCell(g), h("td", {cls:"num", text:days(g.age)}), h("td", {cls:"num", text:fmt(g.playing)}),
        h("td", {cls:"num", text:trend(g.growth_24h)}), h("td", null, g.wave ? [badge(g.wave_stage), " " + g.wave] : "—"));
    })) : h("p", {cls:"empty", text:D.history_hours < 24 ? "Needs a day of history: check back tomorrow." : "Nothing is growing fast right now."}));
  } else if (state.tab === "charts"){
    var cs = D.charts.filter(gameMatches);
    list.appendChild(cs.length ? table([{t:"Game"},{t:"Chart"},{t:"Position",num:1},{t:"Age",num:1},{t:"Playing",num:1}], cs.map(function(g){
      return h("tr", null, gameCell(g), h("td", {text:g.chart}), h("td", {cls:"num", text:g.position ? "#" + g.position : "—"}),
        h("td", {cls:"num", text:days(g.age)}), h("td", {cls:"num", text:fmt(g.playing)}));
    })) : h("p", {cls:"empty", text:"No new chart entries in the last 24 hours."}));
  } else if (state.tab === "mechanics"){
    list.appendChild(D.mechanics.length ? table([{t:"Mechanic"},{t:"Young games",num:1},{t:"Reached 1K"},{t:"New this week",num:1},{t:"Last week",num:1},{t:"Biggest right now"}],
      D.mechanics.map(function(m){
        var up = m.new_this_week > m.new_last_week ? " ↑" : m.new_this_week < m.new_last_week ? " ↓" : "";
        return h("tr", null, h("td", {text:m.name}), h("td", {cls:"num", text:String(m.games)}),
          h("td", null, m.hits + "/" + m.eligible + " (" + pct(m.hit_rate) + ")", hbar(m.hit_rate)),
          h("td", {cls:"num", text:m.new_this_week + up}), h("td", {cls:"num", text:String(m.new_last_week)}),
          h("td", {cls:"wrap"}, h("div", {cls:"chips"}, m.top.map(chip))));
      })) : h("p", {cls:"empty", text:"Not enough games yet."}));
  } else if (state.tab === "track"){
    renderTrack(list);
  } else {
    var ws = D.waves.filter(function(w){ return w.stage === state.tab && waveMatches(w); });
    if (!ws.length) list.appendChild(h("p", {cls:"empty", text:state.q || state.lineage ? "No waves match." : "Nothing here right now."}));
    ws.forEach(function(w){ list.appendChild(waveCard(w)); });
  }
}

function renderOpps(){
  var box = document.getElementById("opps"); box.textContent = "";
  if (!D.opportunities.length) { box.appendChild(h("p", {cls:"empty", text:"No open waves or breakouts right now."})); return; }
  D.opportunities.forEach(function(o, i){
    var target = o.kind === "wave" ? function(){ go(o.stage, "w-" + o.key); } : function(){ go("lone"); };
    box.appendChild(h("button", {cls:"opp", type:"button", on:{click:target}},
      h("span", {cls:"rank", text:String(i + 1)}), icon(o.leader),
      h("div", {style:"min-width:0;flex:1"},
        h("div", {cls:"row", style:"justify-content:space-between;gap:8px;flex-wrap:wrap"}, h("span", {cls:"name", text:o.label}), badge(o.stage)),
        h("div", {cls:"why", text:o.why.join(" · ")}),
        h("div", {cls:"scorebar", title:"Opportunity score " + o.score + "/100"}, h("span", {style:"width:" + o.score + "%"})))));
  });
}
function renderMine(){
  var box = document.getElementById("mine");
  if (!D.mine.length) { document.getElementById("mine-h").style.display = "none"; return; }
  D.mine.forEach(function(g){
    box.appendChild(h("span", {cls:"chip", title:g.wave ? "Part of the “" + g.wave + "” wave" : "Not part of a wave"}, link(g, icon(g)),
      h("span", {cls:"t", text:g.name}), h("span", {cls:"s", text:fmt(g.playing) + " playing"}),
      g.wave ? h("span", {cls:"badge b-" + g.wave_stage, text:g.wave + ": " + (STAGE_NAMES[g.wave_stage] || "").replace(/^\S+\s/, "")}) : h("span", {cls:"badge b-none", text:"not in a wave"})));
  });
}
function header(){
  var hrs = D.history_hours || 0;
  var hist = hrs >= 24 ? (hrs/24).toFixed(1) + " days of history" : Math.round(hrs) + " hours of history";
  document.getElementById("meta").textContent = "Updated " + (D.updated_label || "—") + " · checks every 3 hours · " +
    (D.games_tracked || 0).toLocaleString() + " games tracked · " + hist;
  var notes = document.getElementById("notes");
  if (D.incomplete) notes.appendChild(h("div", {cls:"note warn", text:"⚠️ The last check was incomplete (" + D.incomplete + "). The next check usually fills the gap."}));
  if (D.search && D.search.done < D.search.planned) notes.appendChild(h("div", {cls:"note",
    text:"This check ran " + D.search.done + " of " + D.search.planned + " searches (Roblox limits searches from cloud servers). Hot-wave words go first; every game found stays tracked."}));
  if (hrs < 24) notes.appendChild(h("div", {cls:"note", text:"Growth, momentum and visits-per-day numbers start once there's a day of history. Stages already work from how the copies are doing."}));
}
function footer(){
  var r = D.rules || {};
  document.getElementById("foot").appendChild(h("div", null,
    h("h3", {text:"How the stages are decided"}),
    h("ul", null,
      h("li", {text:"A wave is a group of games made in the last " + r.wave_window_days + " days whose titles share an idea (ragdoll, steal, for animals…)."}),
      h("li", {text:"“Copies reached 1K+” counts how many of the wave's newer games (3+ days old) reached 1,000 players at once. Most copies succeeding means players want more; most failing means it's crowded."}),
      h("li", {text:"🟢 Jump in now: at least " + r.jump_min_hits + " copies reached 1K+, at least " + pct(r.jump_hit_rate) + " of copies succeed, the leader is under " + r.jump_max_age_days + " days old, and players aren't falling."}),
      h("li", {text:"🌱 Just starting: leader under " + r.starting_max_age_days + " days old with at most " + r.starting_max_games + " games so far."}),
      h("li", {text:"🔴 Crowded: under " + pct(r.crowded_hit_rate) + " of copies (or of the newest copies) succeed, the leader is over " + r.crowded_age_days + " days old, or " + r.crowded_games + "+ games."}),
      h("li", {text:"⚫ Fading: total players down more than " + Math.round((1 - (r.fading_7d || 0)) * 100) + "% in a week."}),
      h("li", {text:"⭐ Opportunity score: how well copies are doing (newest copies count most) × how young the leader is × 3-day player trend × how much is held by big studios (" + fmt(D.big_members) + "+ members) × a bonus for the tycoon lineage. Lone breakouts score on youth, size and 24-hour growth."})),
    h("h3", {text:"Stand-ins for stats Roblox keeps private"}),
    h("ul", null,
      h("li", {text:"Visits per player: total visits ÷ players who got the game's most common badge (usually the join badge). A rough retention signal: higher means people come back. It's off if the badge was added late."}),
      h("li", {text:"Minutes per visit: average players online × 1,440 ÷ visits per day. Long can mean sticky, or lots of AFK."}),
      h("li", {text:"Progress badges show what share of players reached milestones; badges added in the last 3 weeks usually mean new updates or live events."}),
      h("li", {text:"Mechanics are detected from keywords in titles and descriptions, so they're rough."})),
    h("p", {text:"Not available publicly: real retention, revenue, ad spend, play-through rate. Data comes from Roblox's public charts and search, checked every 3 hours; the radar only sees games that show up there. It tells you when a wave is open; the idea and the twist are still yours."})));
}

var hash = (location.hash || "").slice(1);
if (TABS.some(function(s){ return s.id === hash; })) state.tab = hash;
else if (!D.waves.some(function(w){ return w.stage === "jump"; })) state.tab = D.waves.some(function(w){ return w.stage === "starting"; }) ? "starting" : "lone";
document.getElementById("q").addEventListener("input", function(e){ state.q = e.target.value.trim().toLowerCase(); render(); });
document.getElementById("lineage").addEventListener("change", function(e){ state.lineage = e.target.checked; render(); });
header(); renderOpps(); renderMine(); footer(); render();
})();
</script>
</body>
</html>
"""
