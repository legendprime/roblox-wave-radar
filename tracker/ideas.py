"""Private idea check: is a game idea you're considering already on Roblox, and how big is it?

Ideas live in ideas.toml, which is kept out of git on purpose: the repository and the radar
website are public, and an idea list is exactly what you don't want to publish. This runs only
when you ask (python3 -m tracker ideas); it searches Roblox for each idea, keeps the games whose
titles match, and says whether the lane is open. It remembers the last check, so a game that
appeared since then is flagged: that's the early warning that someone shipped it first."""
import datetime as dt
import json
import re
import tomllib

from .api import ApiError
from .db import ROOT, now, parse_iso
from .report import REPORTS, compact

IDEAS_PATH = ROOT / "ideas.toml"
# The biggest matching game decides the verdict. Under 100 players it's "open" only if hardly anyone
# has tried: three or more tiny attempts means the obvious version was made and didn't catch on.
VERDICTS = [(1000, "🟡 being tried, still small"), (10000, "🟠 taken (mid-size)"), (float("inf"), "🔴 taken")]
OPEN, FLOPPED = "🟢 open, untried", "⚪ tried, none took off"


def load(path=None):
    path = path or IDEAS_PATH
    with open(path, "rb") as f:
        ideas = tomllib.load(f).get("idea", [])
    for i in ideas:
        i.setdefault("queries", [i["name"]])
        # By default a title matches when it contains every word of the first query.
        i.setdefault("match", [re.escape(w) for w in i["queries"][0].lower().split()])
    return ideas


def matches(idea, title):
    t = (title or "").lower()
    return all(re.search(rx, t) for rx in idea["match"])


def verdict(biggest, attempts=0):
    if biggest < 100:
        return FLOPPED if attempts >= 3 else OPEN
    for limit, label in VERDICTS:
        if biggest < limit:
            return label


def check(api, ideas, previous=None, log=print):
    """One search per query; returns a result per idea with its matching games, biggest first."""
    previous = previous or {}
    out = []
    for idea in ideas:
        found = {}
        for q in idea["queries"]:
            try:
                for g in api.search(q, 1):
                    uid = g.get("universeId")
                    if uid and matches(idea, g.get("name")):
                        p = g.get("playerCount") or 0
                        if uid not in found or p > found[uid]["playing"]:
                            found[uid] = {"uid": uid, "name": g.get("name"), "playing": p,
                                          "place": g.get("rootPlaceId")}
            except ApiError as e:
                log(f"  ! search '{q}': {e}")
        games = sorted(found.values(), key=lambda g: -g["playing"])
        try:
            created = {d["id"]: d.get("created") for d in api.games([g["uid"] for g in games[:20]])} if games else {}
        except ApiError:
            created = {}
        t = now()
        for g in games:
            c = parse_iso(created.get(g["uid"]))
            g["age"] = (t - c).total_seconds() / 86400 if c else None
        seen_before = previous.get(idea["name"])
        fresh = [g for g in games if seen_before is not None and g["uid"] not in seen_before and g["playing"] >= 20]
        biggest = games[0]["playing"] if games else 0
        out.append({"name": idea["name"], "proof": idea.get("proof", ""), "games": games, "biggest": biggest,
                    "verdict": verdict(biggest, len(games)), "new_since_last": fresh,
                    "just_shipped": [g for g in games if g["age"] is not None and g["age"] <= 14 and g["playing"] >= 100]})
    return out


def render(results, when):
    lines = [f"# Idea check: {when}", "",
             "Private: this file stays on this computer. The verdict comes from the biggest matching game on Roblox "
             "right now: 🟢 nobody above 100 players and fewer than 3 attempts · ⚪ 3+ attempts, all under 100 "
             "(made, didn't catch on: needs a real twist or much better execution) · 🟡 under 1K · 🟠 under 10K · 🔴 10K+.", ""]
    order = sorted(results, key=lambda r: r["biggest"])
    lines += ["| Idea | Verdict | Matching games | Biggest right now |", "|---|---|---|---|"]
    for r in order:
        top = r["games"][0] if r["games"] else None
        big = f"{top['name']} ({compact(top['playing'])})" if top else "none found"
        flag = " ⚠️ new since last check" if r["new_since_last"] else ""
        lines.append(f"| **{r['name']}** | {r['verdict']}{flag} | {len(r['games'])} | {big} |")
    lines.append("")
    for r in order:
        lines += [f"## {r['name']}: {r['verdict']}", ""]
        if r["proof"]:
            lines += [f"Why it should work: {r['proof']}", ""]
        if r["new_since_last"]:
            lines += ["⚠️ Appeared since the last check: " + ", ".join(
                f"{g['name']} ({compact(g['playing'])})" for g in r["new_since_last"]), ""]
        if not r["games"]:
            lines += ["No game with a matching title came up in Roblox search.", ""]
            continue
        for g in r["games"][:8]:
            age = f", {g['age']:.0f} days old" if g["age"] is not None else ""
            url = f"https://www.roblox.com/games/{g['place']}" if g.get("place") else ""
            lines.append(f"- {g['name']}: {compact(g['playing'])} playing{age} {url}".rstrip())
        lines.append("")
    return "\n".join(lines)


def run(conn, api, path=None, log=print):
    path = path or IDEAS_PATH
    try:
        ideas = load(path)
    except FileNotFoundError:
        print(f"No idea list yet. Copy ideas.example.toml to {path} and put your ideas in it "
              "(it's ignored by git, so it stays private).")
        return 1
    if not ideas:
        print(f"{path} has no [[idea]] entries.")
        return 1
    row = conn.execute("SELECT value FROM meta WHERE key = 'ideas_last'").fetchone()
    previous = json.loads(row[0]) if row and row[0] else {}
    results = check(api, ideas, previous, log=log)
    for r in results:
        previous[r["name"]] = sorted(set(previous.get(r["name"], [])) | {g["uid"] for g in r["games"]})
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('ideas_last', ?)", (json.dumps(previous),))
    conn.commit()
    when = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    text = render(results, when)
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / "ideas.md"
    out.write_text(text, encoding="utf-8")
    for r in sorted(results, key=lambda r: r["biggest"]):
        top = r["games"][0] if r["games"] else None
        flag = "  ⚠️ NEW: " + ", ".join(g["name"] for g in r["new_since_last"]) if r["new_since_last"] else ""
        print(f"{r['verdict']:<30} {r['name'][:44]:<45} "
              + (f"biggest: {top['name'][:40]} ({compact(top['playing'])}), {len(r['games'])} matching" if top
                 else "nothing matching") + flag)
    print(f"\nfull list: {out}")
    return 0
