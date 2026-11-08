"""Builds the radar website: site/index.html (everything inside one page) + site/waves.json.
GitHub Pages serves the site/ folder; see .github/workflows/radar.yml."""
import datetime as dt
import json
from zoneinfo import ZoneInfo

from .config import watchlist
from .db import ROOT, iso

SITE = ROOT / "site"
SPARK_DAYS = 14


def _num(x):
    return None if x is None else round(x, 3)


class SiteData:
    def __init__(self, radar, conn, cfg):
        self.R, self.conn, self.cfg = radar, conn, cfg
        self.days = [(radar.t - dt.timedelta(days=d)).strftime("%Y-%m-%d") for d in range(SPARK_DAYS - 1, -1, -1)]

    def game(self, uid):
        R = self.R
        g = R.games.get(uid)
        icon = g["icon_url"] if g and g["icon_url"] and str(g["icon_url"]).startswith("https://tr.rbxcdn.com/") else None
        genre = " / ".join(x for x in ((g["genre_l1"], g["genre_l2"]) if g else ()) if x)
        return {"id": uid, "name": (g["name"] if g else None) or str(uid),
                "place": g["root_place_id"] if g else None, "icon": icon,
                "playing": R.playing(uid), "peak": (g["peak_playing"] if g else None),
                "age": _num(R.age(uid)), "genre": genre, "growth_24h": _num(R.growth([uid], 24))}

    def spark(self, uids):
        if not uids:
            return []
        marks = ",".join(str(int(u)) for u in uids)
        rows = dict(self.conn.execute(
            f"SELECT day, SUM(peak_playing) FROM daily WHERE universe_id IN ({marks}) AND day >= ? GROUP BY day",
            (self.days[0],)).fetchall())
        return [{"day": d, "total": rows.get(d)} for d in self.days]

    def wave(self, w, members_limit):
        everyone = set(w["members"]) | {w["leader"]}
        keys = ("key", "label", "stage", "why", "parent", "terms", "n", "n7", "n14", "hits", "hits10", "eligible",
                "recent", "recent_hits", "total", "genre", "lineage")
        out = {k: w.get(k) for k in keys}
        out.update({
            "hit_rate": _num(w["hit_rate"]), "recent_hit_rate": _num(w.get("recent_hit_rate")),
            "growth_24h": _num(w["growth_24h"]), "growth_72h": _num(w["growth_72h"]), "growth_7d": _num(w["growth_7d"]),
            "leader_age": _num(w["leader_age"]), "concentration": _num(w["concentration"]),
            "spark": self.spark(everyone),
            "leader": self.game(w["leader"]),
            "best": [self.game(u) for u in w["best"]],
            "newest": [self.game(u) for u in w["newest"]],
            "members": [self.game(u) for u in w["members"][:members_limit]],
        })
        return out

    def build(self):
        R, r = self.R, self.cfg["radar"]
        tz = ZoneInfo(r["timezone"])
        show = []
        for w in R.waves:
            if w["stage"] in ("jump", "starting", "fading"):
                show.append(self.wave(w, 80))
            elif w["stage"] == "crowded" and w["total"] >= r["show_crowded_min_total"] \
                    and (w["leader_age"] or 0) <= r["show_crowded_max_leader_age"]:
                show.append(self.wave(w, 30))
            elif w["stage"] == "watching" and w["n"] >= 5:
                show.append(self.wave(w, 20))
        lone = []
        for x in R.lone:
            g = self.game(x["uid"])
            g.update({"lookalikes": x["n_copies"], "lookalike_games": [self.game(u) for u in x["copies"]]})
            lone.append(g)
        mine = [self.game(uid) for uid, w in watchlist(self.conn, self.cfg).items() if w["kind"] == "mine"]
        mine.sort(key=lambda g: g["playing"] or 0, reverse=True)
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
            "waves": show, "lone": lone, "mine": mine,
        }


def write(radar, conn, cfg, log=print):
    data = SiteData(radar, conn, cfg).build()
    SITE.mkdir(exist_ok=True)
    blob = json.dumps(data, separators=(",", ":"), default=str)
    (SITE / "waves.json").write_text(blob, encoding="utf-8")
    safe = blob.replace("</", "<\\/")  # can't close the <script> tag early
    (SITE / "index.html").write_text(PAGE.replace("/*DATA*/null", safe), encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    log(f"website written: {SITE / 'index.html'} ({len(blob) / 1024:.0f} KB of data)")
    return SITE / "index.html"


def site_games(radar):
    """Every game the website shows, so their icons can be fetched."""
    uids = set()
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
  --accent:#2563eb;--spark:#2563eb;--shadow:0 1px 2px rgba(0,0,0,.05),0 2px 8px rgba(0,0,0,.04);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#121212;--panel:#1b1b1d;--ink:#ecebe8;--muted:#a3a19c;--line:#2c2c30;--soft:#232326;
    --jump:#4ade80;--jump-bg:#13291b;--start:#fbbf24;--start-bg:#2b2310;--crowd:#f87171;--crowd-bg:#2e1515;
    --fade:#a1a1aa;--fade-bg:#232326;--watch:#9ca3af;--watch-bg:#232326;--lone:#c4b5fd;--lone-bg:#231b38;
    --accent:#60a5fa;--spark:#60a5fa;--shadow:none;
  }
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
a{color:inherit;text-decoration:none}
a:hover{color:var(--accent)}
main{max-width:1120px;margin:0 auto;padding:20px 16px 72px}
header h1{font-size:26px;line-height:1.2;margin:0 0 4px;letter-spacing:-.01em}
.meta{color:var(--muted);font-size:13.5px;margin:0}
.notes{margin:12px 0 0;display:grid;gap:6px}
.note{background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:8px 12px;font-size:13.5px;color:var(--muted)}
.note.warn{border-color:var(--start);color:var(--ink)}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0 12px}
.tab{appearance:none;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:999px;
  padding:7px 14px;font:inherit;font-size:14px;cursor:pointer;display:inline-flex;gap:6px;align-items:center}
.tab[aria-pressed="true"]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.tab .n{font-variant-numeric:tabular-nums;opacity:.75}
.controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:18px}
.controls input[type=search]{flex:1 1 220px;min-width:0;border:1px solid var(--line);background:var(--panel);color:var(--ink);
  border-radius:10px;padding:9px 12px;font:inherit}
.controls label{display:inline-flex;gap:6px;align-items:center;font-size:14px;color:var(--muted);cursor:pointer}
.section-intro{color:var(--muted);margin:0 0 14px;max-width:820px}
.grid{display:grid;gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:var(--shadow);min-width:0}
.card-top{display:flex;gap:12px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}
.card h2{font-size:21px;margin:0;line-height:1.25;word-break:break-word}
.badge{display:inline-block;font-size:12.5px;font-weight:600;border-radius:999px;padding:3px 10px;white-space:nowrap}
.b-jump{color:var(--jump);background:var(--jump-bg)}.b-starting{color:var(--start);background:var(--start-bg)}
.b-crowded{color:var(--crowd);background:var(--crowd-bg)}.b-fading{color:var(--fade);background:var(--fade-bg)}
.b-watching{color:var(--watch);background:var(--watch-bg)}.b-lone{color:var(--lone);background:var(--lone-bg)}
.pocket{font-size:13px;color:var(--muted);margin:6px 0 0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:14px 0 10px}
.stat{background:var(--soft);border-radius:10px;padding:8px 10px;min-width:0}
.stat .v{font-size:19px;font-weight:650;font-variant-numeric:tabular-nums;line-height:1.2}
.stat .k{font-size:12px;color:var(--muted)}
.why{font-size:13.5px;color:var(--muted);margin:2px 0 12px}
.spark{display:flex;align-items:flex-end;gap:10px;margin:0 0 12px}
.spark svg{width:100%;max-width:340px;height:56px;display:block}
.spark .cap{font-size:12px;color:var(--muted);white-space:nowrap}
.row{display:flex;gap:10px;align-items:center;min-width:0}
.label{font-size:12.5px;color:var(--muted);margin:10px 0 6px;font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.leader{display:flex;gap:12px;align-items:center;background:var(--soft);border-radius:12px;padding:10px;min-width:0}
.leader img,.leader .ph{width:48px;height:48px;border-radius:10px;flex:none;background:var(--line);object-fit:cover}
.leader .name{font-weight:600;word-break:break-word}
.sub{font-size:13px;color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{display:inline-flex;gap:8px;align-items:center;border:1px solid var(--line);border-radius:10px;padding:5px 9px 5px 5px;
  max-width:100%;min-width:0;background:var(--panel)}
.chip img,.chip .ph{width:26px;height:26px;border-radius:6px;flex:none;background:var(--line);object-fit:cover}
.chip .t{font-size:13.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:220px}
.chip .s{font-size:12.5px;color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums}
.more{appearance:none;border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:10px;padding:7px 12px;
  font:inherit;font-size:13.5px;cursor:pointer;margin-top:12px}
.tablewrap{overflow-x:auto;margin-top:10px;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em;background:var(--soft)}
tr:last-child td{border-bottom:0}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
td.g{white-space:normal;min-width:180px}
td.g .row img,td.g .row .ph{width:24px;height:24px;border-radius:6px;flex:none;background:var(--line)}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.tile{display:flex;gap:12px;align-items:flex-start;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px;min-width:0}
.tile img,.tile .ph{width:64px;height:64px;border-radius:12px;flex:none;background:var(--line);object-fit:cover}
.tile .name{font-weight:600;word-break:break-word;line-height:1.3}
.empty{color:var(--muted);font-style:italic;padding:12px 0}
footer{margin-top:40px;color:var(--muted);font-size:13.5px;border-top:1px solid var(--line);padding-top:18px}
footer h3{color:var(--ink);font-size:15px;margin:0 0 8px}
footer ul{margin:0 0 12px;padding-left:18px}
@media (max-width:560px){ header h1{font-size:22px} .card h2{font-size:19px} .chip .t{max-width:150px} }
</style>
</head>
<body>
<main>
  <header>
    <h1>📡 Roblox Wave Radar</h1>
    <p class="meta" id="meta"></p>
    <div class="notes" id="notes"></div>
  </header>
  <nav class="tabs" id="tabs" aria-label="Stages"></nav>
  <div class="controls">
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
var D = JSON.parse(document.getElementById("data").textContent) || {waves:[],lone:[],mine:[]};
var STAGES = [
  {id:"jump", name:"Jump in now", emoji:"🟢", intro:"Copies with a twist are succeeding and it isn't crowded yet. This is the window, and it lasts weeks, not months."},
  {id:"starting", name:"Just starting", emoji:"🌱", intro:"A young game is breaking out and only a few copies exist. If the copies start succeeding, it moves to Jump in now."},
  {id:"lone", name:"Lone breakouts", emoji:"👀", intro:"Young games pulling big numbers with no wave around them yet. The next wave usually starts as one of these."},
  {id:"crowded", name:"Crowded", emoji:"🔴", intro:"The wave is real but the window has closed: copies mostly fail, or the leader is old. Only a big change (new theme plus a reworked loop) has a shot."},
  {id:"fading", name:"Fading", emoji:"⚫", intro:"Total players are falling."},
  {id:"watching", name:"Watching", emoji:"·", intro:"Groups that don't meet any stage yet."},
  {id:"mine", name:"Your games", emoji:"🧑‍💻", intro:"Your games from the watchlist."}
];

function h(tag, attrs){
  var el = document.createElement(tag);
  if (attrs) for (var k in attrs){
    if (attrs[k] == null || attrs[k] === false) continue;
    if (k === "text") el.textContent = attrs[k];
    else if (k === "cls") el.className = attrs[k];
    else if (k === "on") for (var ev in attrs.on) el.addEventListener(ev, attrs.on[ev]);
    else el.setAttribute(k, attrs[k]);
  }
  for (var i = 2; i < arguments.length; i++){
    var c = arguments[i];
    if (c == null || c === false) continue;
    if (Array.isArray(c)) c.forEach(function(x){ if (x != null && x !== false) el.appendChild(typeof x === "string" ? document.createTextNode(x) : x); });
    else el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return el;
}
function fmt(n){
  if (n == null) return "—";
  if (n >= 1e6) return (n/1e6).toFixed(2) + "M";
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
function badge(stage){
  var s = STAGES.find(function(x){ return x.id === stage; }) || {name:stage, emoji:""};
  return h("span", {cls:"badge b-" + stage, text:s.emoji + " " + s.name});
}

function spark(points){
  var vals = points.map(function(p){ return p.total; });
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
function gamesTable(list){
  return h("div", {cls:"tablewrap"}, h("table", null,
    h("thead", null, h("tr", null, h("th", {text:"Game"}), h("th", {cls:"num", text:"Age"}), h("th", {cls:"num", text:"Playing"}),
      h("th", {cls:"num", text:"Peak seen"}), h("th", {cls:"num", text:"24h"}), h("th", {text:"Genre"}))),
    h("tbody", null, list.map(function(g){
      return h("tr", null, h("td", {cls:"g"}, link(g, h("span", {cls:"row"}, icon(g), h("span", {text:g.name})))),
        h("td", {cls:"num", text:days(g.age)}), h("td", {cls:"num", text:fmt(g.playing)}), h("td", {cls:"num", text:fmt(g.peak)}),
        h("td", {cls:"num", text:trend(g.growth_24h)}), h("td", {text:g.genre || "—"}));
    }))));
}

function waveCard(w){
  var stats = h("div", {cls:"stats"},
    h("div", {cls:"stat"}, h("div", {cls:"v", text:(w.eligible ? w.hits + "/" + w.eligible : "—")}), h("div", {cls:"k", text:"copies reached 1K+ (" + pct(w.hit_rate) + ")"})),
    h("div", {cls:"stat"}, h("div", {cls:"v", text:(w.recent ? w.recent_hits + "/" + w.recent : "—")}), h("div", {cls:"k", text:"newest copies at 1K+"})),
    h("div", {cls:"stat"}, h("div", {cls:"v", text:String(w.n)}), h("div", {cls:"k", text:w.n7 + " new this week, " + w.n14 + " in 2 weeks"})),
    h("div", {cls:"stat"}, h("div", {cls:"v", text:fmt(w.total)}), h("div", {cls:"k", text:"playing now · 3-day " + trend(w.growth_72h)})),
    h("div", {cls:"stat"}, h("div", {cls:"v", text:days(w.leader_age)}), h("div", {cls:"k", text:"leader's age"})));
  var L = w.leader;
  var body = [
    h("div", {cls:"card-top"}, h("div", null, h("h2", {text:w.label}),
      w.parent ? h("p", {cls:"pocket", text:"A hot pocket inside the bigger “" + w.parent + "” wave, which is past its window."}) : null),
      badge(w.stage)),
    stats,
    h("p", {cls:"why", text:"Why: " + w.why + (w.lineage ? " · in the tycoon lineage" : " · " + (w.genre || "") + " (a part to borrow)")}),
    spark(w.spark || []),
    h("div", {cls:"label", text:"Leader"}),
    link(L, h("div", {cls:"leader"}, icon(L), h("div", {style:"min-width:0"}, h("div", {cls:"name", text:L.name}),
      h("div", {cls:"sub", text:fmt(L.playing) + " playing · " + days(L.age) + " old · 24h " + trend(L.growth_24h)}))))
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

function tile(g, extra){
  return link(g, h("div", {cls:"tile"}, icon(g), h("div", {style:"min-width:0"}, h("div", {cls:"name", text:g.name}),
    h("div", {cls:"sub", text:fmt(g.playing) + " playing · " + days(g.age) + " old" + (g.growth_24h != null ? " · 24h " + trend(g.growth_24h) : "")}),
    extra ? h("div", {cls:"sub", text:extra}) : null,
    h("div", {cls:"sub", text:g.genre || ""}))));
}

var state = {tab:"jump", q:"", lineage:false};
function matches(w){
  var q = state.q;
  if (state.lineage && !w.lineage) return false;
  if (!q) return true;
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
  if (id === "mine") return D.mine.length;
  return D.waves.filter(function(w){ return w.stage === id && matches(w); }).length;
}
function renderTabs(){
  var nav = document.getElementById("tabs"); nav.textContent = "";
  STAGES.forEach(function(s){
    if (s.id === "mine" && !D.mine.length) return;
    if ((s.id === "fading" || s.id === "watching") && !D.waves.some(function(w){ return w.stage === s.id; })) return;
    nav.appendChild(h("button", {cls:"tab", type:"button", "aria-pressed":String(state.tab === s.id),
      on:{click:function(){ state.tab = s.id; history.replaceState(null, "", "#" + s.id); render(); }}},
      s.emoji + " " + s.name, h("span", {cls:"n", text:String(count(s.id))})));
  });
}
function render(){
  renderTabs();
  var s = STAGES.find(function(x){ return x.id === state.tab; }) || STAGES[0];
  document.getElementById("intro").textContent = s.intro;
  var list = document.getElementById("list"); list.textContent = "";
  if (state.tab === "lone"){
    var lone = D.lone.filter(gameMatches);
    if (!lone.length) list.appendChild(h("p", {cls:"empty", text:"Nothing here right now."}));
    else list.appendChild(h("div", {cls:"tiles"}, lone.map(function(g){
      return tile(g, g.lookalikes ? g.lookalikes + " lookalike" + (g.lookalikes > 1 ? "s" : "") + " so far" : "No lookalikes yet");
    })));
    return;
  }
  if (state.tab === "mine"){
    list.appendChild(D.mine.length ? gamesTable(D.mine) : h("p", {cls:"empty", text:"No games on your watchlist."}));
    return;
  }
  var ws = D.waves.filter(function(w){ return w.stage === state.tab && matches(w); });
  if (!ws.length){ list.appendChild(h("p", {cls:"empty", text:state.q || state.lineage ? "No waves match." : "Nothing here right now."})); return; }
  ws.forEach(function(w){ list.appendChild(waveCard(w)); });
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
  if (hrs < 24) notes.appendChild(h("div", {cls:"note", text:"Growth and trend numbers start once there's a day of history. Stages already work from how the copies are doing."}));
}
function footer(){
  var r = D.rules || {};
  document.getElementById("foot").appendChild(h("div", null,
    h("h3", {text:"How to read this"}),
    h("ul", null,
      h("li", {text:"A wave is a group of games made in the last " + r.wave_window_days + " days whose titles share an idea (ragdoll, steal, for animals…)."}),
      h("li", {text:"“Copies reached 1K+” counts how many of the wave's newer games (3+ days old) reached 1,000 players at once. Most copies succeeding means players want more; most failing means it's crowded."}),
      h("li", {text:"🟢 Jump in now: at least " + r.jump_min_hits + " copies reached 1K+, at least " + pct(r.jump_hit_rate) + " of copies succeed, the leader is under " + r.jump_max_age_days + " days old, and players aren't falling."}),
      h("li", {text:"🌱 Just starting: leader under " + r.starting_max_age_days + " days old with at most " + r.starting_max_games + " games so far."}),
      h("li", {text:"🔴 Crowded: under " + pct(r.crowded_hit_rate) + " of copies (or of the newest copies) succeed, the leader is over " + r.crowded_age_days + " days old, or " + r.crowded_games + "+ games."}),
      h("li", {text:"⚫ Fading: total players down more than " + Math.round((1 - (r.fading_7d || 0)) * 100) + "% in a week."})),
    h("p", {text:"Data: Roblox's public charts and search, checked every 3 hours. The radar only sees games that show up there, and grouping by title words is rough. It tells you when a wave is open; the idea and the twist are still yours."})));
}

var hash = (location.hash || "").slice(1);
if (STAGES.some(function(s){ return s.id === hash; })) state.tab = hash;
else if (!D.waves.some(function(w){ return w.stage === "jump"; })) state.tab = D.waves.some(function(w){ return w.stage === "starting"; }) ? "starting" : "lone";
document.getElementById("q").addEventListener("input", function(e){ state.q = e.target.value.trim().toLowerCase(); render(); });
document.getElementById("lineage").addEventListener("change", function(e){ state.lineage = e.target.checked; render(); });
header(); footer(); render();
})();
</script>
</body>
</html>
"""
