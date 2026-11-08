"""Renders the radar as DASHBOARD.md (readable on GitHub, phone included) and waves.json."""
import datetime as dt
import json
from zoneinfo import ZoneInfo

from .config import watchlist
from .report import REPORTS, compact, fmt_days

STAGE_TITLE = {
    "jump": "🟢 Jump in now",
    "starting": "🌱 Just starting",
    "crowded": "🔴 Crowded: too late for a plain copy",
    "fading": "⚫ Fading",
    "watching": "Watching",
}


def esc(s):
    return (s or "").replace("|", "\\|").replace("[", "\\[").replace("]", "\\]").replace("\n", " ").strip()


def growth(g):
    return "—" if g is None else f"×{g:.2f}" if g < 10 else f"×{g:.0f}"


class Page:
    def __init__(self, radar, conn, cfg):
        self.R, self.conn, self.cfg = radar, conn, cfg
        self.tz = ZoneInfo(cfg["radar"]["timezone"])

    def link(self, uid, icon=False):
        g = self.R.games.get(uid)
        name = esc(g["name"] if g else str(uid)) or str(uid)
        img = f'<img src="{g["icon_url"]}" width="18" height="18"> ' if icon and g and g["icon_url"] else ""
        if g and g["root_place_id"]:
            return f"{img}[{name}](https://www.roblox.com/games/{g['root_place_id']})"
        return img + name

    def game_bits(self, uid):
        return f"{self.link(uid)} {compact(self.R.playing(uid))} ({fmt_days(self.R.age(uid))})"

    def card(self, w):
        R = self.R
        hit = (f"**{w['hits']} of {w['eligible']} copies reached 1K+ players**" if w["eligible"]
               else "**no copies old enough to judge yet**")
        lines = [f"### {w['label']}",
                 f"{hit} · {w['n']} games · {w['n7']} new this week, {w['n14']} in two weeks · "
                 f"{compact(w['total'])} playing {w['spark']} · 3-day trend {growth(w['growth_72h'])}",
                 ""]
        if w.get("parent"):
            lines += [f"> A hot pocket inside the bigger **{w['parent']}** wave, which is past its window. "
                      f"This corner of it is still open.", ""]
        lines += [
                 f"- **Leader:** {self.link(w['leader'], icon=True)} · {compact(w['leader_playing'])} playing · "
                 f"{fmt_days(w['leader_age'])} old · 24h {growth(w['leader_growth_24h'])}"]
        if w["best"]:
            lines.append("- **Doing best after it:** " + " · ".join(self.game_bits(u) for u in w["best"]))
        if w["newest"]:
            lines.append("- **Newest copies (this week):** " + " · ".join(self.game_bits(u) for u in w["newest"]))
        others = [x for x in w["terms"] if x != w["label"]]
        if others:
            lines.append("- **Other title words in this wave:** " + ", ".join(others[:6]))
        lineage = "yes, it's in the tycoon lineage" if w["lineage"] else "not in the tycoon lineage yet (a part to borrow)"
        lines.append(f"- **Genre:** {w['genre']}: {lineage}")
        lines.append(f"- **Why this stage:** {w['why']}")
        return "\n".join(lines)

    def render(self):
        R, r = self.R, self.cfg["radar"]
        t_local = R.t.astimezone(self.tz)
        by = {s: [w for w in R.waves if w["stage"] == s] for s in STAGE_TITLE}
        n_games = self.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        hist = R.history_hours
        hist_txt = (f"{hist / 24:.1f} days of history" if hist >= 24
                    else "under an hour of history" if hist < 1.5 else f"{hist:.0f} hours of history")
        out = ["# 📡 Roblox Wave Radar", "",
               f"_Updated {t_local.strftime('%a %b %-d, %-I:%M %p %Z')} · checks every 3 hours · "
               f"{n_games:,} games tracked · {hist_txt}_", ""]
        last = self.conn.execute(
            "SELECT status, errors FROM runs WHERE status IN ('ok','partial') ORDER BY id DESC LIMIT 1").fetchone()
        if last and last["errors"]:
            first = last["errors"].splitlines()[0]
            out += [f"> ⚠️ The last check was incomplete ({esc(first)[:160]}). The next check usually fills the gap; "
                    f"until then, copy counts may be low.", ""]
        srow = self.conn.execute("SELECT value FROM meta WHERE key = 'last_search'").fetchone()
        if srow and srow[0]:
            s = json.loads(srow[0])
            if s["done"] < s["planned"]:
                per_run = max(1, s["fixed_done"])
                out += [f"> This check ran {s['done']} of {s['planned']} searches: Roblox limits searches from "
                        f"cloud servers. Hot-wave words go first every time; the fixed list of "
                        f"{s['fixed_total']} words cycles every ~{-(-s['fixed_total'] // per_run)} checks, and every "
                        f"game found stays tracked.", ""]
        if hist < 24:
            out += ["> Growth and trend numbers start once there's a day of history. Stages already "
                    "work from how the copies are doing.", ""]

        def names(ws):
            return ", ".join(f"**{w['label']}**" for w in ws[:6]) or "none"
        out += [f"**Right now →** 🟢 Jump in now: {names(by['jump'])} · 🌱 Just starting: {names(by['starting'])} · "
                f"👀 Lone breakouts: {len(R.lone)}", ""]

        for stage, intro in [
                ("jump", "Copies with a twist are succeeding and it isn't crowded yet. This is the window, "
                         "and it lasts weeks, not months."),
                ("starting", "A young game is breaking out and only a few copies exist. Watch closely: "
                             "if the copies start succeeding, it moves to Jump in now.")]:
            out += [f"## {STAGE_TITLE[stage]}", "", f"_{intro}_", ""]
            if not by[stage]:
                out += ["_Nothing right now._", ""]
            for w in by[stage]:
                out += [self.card(w), ""]

        out += ["## 👀 Lone breakouts: possible next waves", "",
                "_Young games pulling big numbers with no wave around them yet. The next wave usually "
                "starts as one of these. The more copies appear, the sooner it becomes a wave._", ""]
        if R.lone:
            out += ["| Game | Age | Playing | 24h | Lookalikes so far | Genre |", "|---|---|---|---|---|---|"]
            for x in R.lone:
                copies = str(x["n_copies"]) + ((": " + ", ".join(self.link(u) for u in x["copies"][:2]))
                                               if x["copies"] else "")
                out.append(f"| {self.link(x['uid'], icon=True)} | {fmt_days(x['age'])} | {compact(x['playing'])} | "
                           f"{growth(x['growth_24h'])} | {copies} | {esc(x['genre'])} |")
        else:
            out.append("_None right now._")
        out.append("")

        crowded = sorted([w for w in by["crowded"] if w["total"] >= r["show_crowded_min_total"]
                          and (w["leader_age"] or 0) <= r["show_crowded_max_leader_age"]],
                         key=lambda w: w["total"], reverse=True)[:r["show_crowded_rows"]]
        out += [f"## {STAGE_TITLE['crowded']}", "",
                "_The wave is real but the window has closed: lots of copies, copies mostly failing, or an old "
                "leader. Only a big change (new theme + reworked loop) has a shot here._", ""]
        if crowded:
            out += ["| Wave | Games | Copies 1K+ | Playing | Leader | Why |", "|---|---|---|---|---|---|"]
            for w in crowded:
                out.append(f"| **{esc(w['label'])}** | {w['n']} | {w['hits']}/{w['eligible']} | {compact(w['total'])} | "
                           f"{self.link(w['leader'])} ({fmt_days(w['leader_age'])}) | {esc(w['why'])} |")
        else:
            out.append("_None._")
        out.append("")

        if by["fading"]:
            out += [f"## {STAGE_TITLE['fading']}", "", "| Wave | Games | Playing | Leader | Why |", "|---|---|---|---|---|"]
            for w in by["fading"]:
                out.append(f"| **{esc(w['label'])}** | {w['n']} | {compact(w['total'])} | {self.link(w['leader'])} | {esc(w['why'])} |")
            out.append("")

        watching = by["watching"]
        if watching:
            out += [f"<details><summary>Watching: {len(watching)} smaller groups (click to open)</summary>", "",
                    "| Wave | Games | Copies 1K+ | Playing | Leader | Note |", "|---|---|---|---|---|---|"]
            for w in watching[:40]:
                out.append(f"| {esc(w['label'])} | {w['n']} | {w['hits']}/{w['eligible']} | {compact(w['total'])} | "
                           f"{self.link(w['leader'])} | {esc(w['why'])} |")
            out += ["", "</details>", ""]

        mine = [uid for uid, w in watchlist(self.conn, self.cfg).items() if w["kind"] == "mine"]
        if mine:
            out += ["## 🧑‍💻 Your games", "", "| Game | Playing | Peak seen | 24h | Age |", "|---|---|---|---|---|"]
            for uid in sorted(mine, key=R.playing, reverse=True):
                g = R.games.get(uid)
                out.append(f"| {self.link(uid)} | {compact(R.playing(uid))} | {compact(g['peak_playing'] if g else None)} | "
                           f"{growth(R.growth([uid], 24))} | {fmt_days(R.age(uid))} |")
            out.append("")

        out += ["## How to read this", "",
                "- A **wave** is a group of games made in the last "
                f"{r['wave_window_days']} days whose titles share an idea (ragdoll, steal, for animals...).",
                f"- **Copies 1K+** counts how many of the wave's newer games (3+ days old) reached 1,000 players. "
                f"If most copies succeed, players want more of this; if most fail, it's crowded.",
                f"- **🟢 Jump in now:** at least {r['jump_min_hits']} copies reached 1K+, at least "
                f"{r['jump_hit_rate']:.0%} of copies succeed, the leader is under {r['jump_max_age_days']} days old, "
                f"and players aren't falling.",
                f"- **🌱 Just starting:** leader under {r['starting_max_age_days']} days old with at most "
                f"{r['starting_max_games']} games so far.",
                f"- **🔴 Crowded:** {r['crowded_games']}+ games, or under {r['crowded_hit_rate']:.0%} of copies "
                f"succeeding, or the leader is over {r['crowded_age_days']} days old.",
                f"- **⚫ Fading:** total players down more than {100 - r['fading_7d'] * 100:.0f}% in a week.",
                "- The radar only sees games that appear in Roblox's charts or search. It adds each hot wave's "
                "words to its next searches so the small copies get counted too.",
                "- None of this guarantees a hit: it tells you **when** a wave is open. The idea and the twist "
                "are still yours.", ""]
        return "\n".join(out)

    def data(self):
        R = self.R

        def g(uid):
            x = R.games.get(uid)
            return {"universe_id": uid, "name": x["name"] if x else None,
                    "place_id": x["root_place_id"] if x else None,
                    "playing": R.playing(uid), "age_days": R.age(uid)}
        waves = []
        for w in R.waves:
            waves.append({k: w[k] for k in ("key", "label", "terms", "stage", "why", "n", "n7", "n14", "hits",
                                            "hits10", "eligible", "hit_rate", "total", "growth_24h", "growth_72h",
                                            "growth_7d", "concentration", "genre", "lineage")}
                         | {"leader": g(w["leader"]), "best": [g(u) for u in w["best"]],
                            "members": [g(u) for u in w["members"][:40]]})
        return {"updated": R.t.isoformat(), "waves": waves,
                "lone_breakouts": [g(x["uid"]) | {"copies": x["n_copies"]} for x in R.lone]}


def write(radar, conn, cfg, log=print):
    page = Page(radar, conn, cfg)
    REPORTS.mkdir(exist_ok=True)
    md_path = REPORTS / "DASHBOARD.md"
    md_path.write_text(page.render(), encoding="utf-8")
    (REPORTS / "waves.json").write_text(json.dumps(page.data(), indent=1, default=str), encoding="utf-8")
    log(f"dashboard written: {md_path}")
    return md_path


def shown_games(radar):
    """Games that appear on the dashboard, so their icons can be fetched."""
    uids = set()
    for w in radar.waves:
        if w["stage"] in ("jump", "starting"):
            uids |= {w["leader"], *w["best"], *w["newest"]}
    uids |= {x["uid"] for x in radar.lone}
    return sorted(uids)
