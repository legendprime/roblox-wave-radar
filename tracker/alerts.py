"""Sends radar alerts as GitHub issues (which GitHub delivers as notifications, phone included).
Outside GitHub Actions it only prints them."""
import json
import os
import urllib.error
import urllib.request

from .db import iso, now
from .report import compact, fmt_days

LABEL = "wave-alert"


def _api(method, path, token, body=None):
    req = urllib.request.Request(
        f"https://api.github.com{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "roblox-wave-radar"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def compose(alert, radar, repo, notify):
    def link(uid):
        g = radar.games.get(uid)
        name = (g["name"] if g else str(uid)) or str(uid)
        return f"[{name}](https://www.roblox.com/games/{g['root_place_id']})" if g and g["root_place_id"] else name

    dash = f"https://github.com/{repo}/tree/radar" if repo else "reports/DASHBOARD.md"
    if alert["kind"] in ("jump", "starting"):
        w = alert["wave"]
        stage = "🟢 Jump in now" if alert["kind"] == "jump" else "🌱 Just starting"
        title = f"{stage}: {w['label']} ({w['n']} games, {w['hits']}/{w['eligible']} copies at 1K+)"
        body = [f"**{w['label']}** just moved to **{stage}**.", "",
                f"- {w['why']}",
                f"- Leader: {link(w['leader'])} · {compact(w['leader_playing'])} playing · {fmt_days(w['leader_age'])} old"]
        if w["best"]:
            body.append("- Doing best after it: " + " · ".join(
                f"{link(u)} {compact(radar.playing(u))}" for u in w["best"][:3]))
        body.append(f"- {w['n']} games so far, {w['n7']} new this week · genre: {w['genre']}")
    else:
        x = alert["lone"]
        name = radar.games[x["uid"]]["name"]
        title = f"👀 Breakout: {name} crossed {compact(alert['value'])} players at {fmt_days(x['age'])} old"
        body = [f"{link(x['uid'])} crossed **{alert['value']:,} players** only {fmt_days(x['age'])} after it was made, "
                f"with {x['n_copies']} copies so far. It could be the start of a new wave.", ""]
    body += ["", f"👉 [Open the dashboard]({dash})"]
    if notify:
        body += ["", f"@{notify}"]
    return title, "\n".join(body)


def send(conn, radar, alerts, log=print):
    if not alerts:
        log("no new alerts")
        return 0
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    notify = os.environ.get("RADAR_NOTIFY")
    sent = 0
    if token and repo:
        try:
            _api("POST", f"/repos/{repo}/labels", token,
                 {"name": LABEL, "color": "1f883d", "description": "New wave or breakout spotted by the radar"})
        except urllib.error.HTTPError:
            pass  # already exists
    for a in alerts:
        title, body = compose(a, radar, repo, notify)
        url = None
        if token and repo:
            try:
                res = _api("POST", f"/repos/{repo}/issues", token, {"title": title, "body": body, "labels": [LABEL]})
                url = res.get("html_url")
                sent += 1
            except urllib.error.HTTPError as e:
                log(f"  ! could not open issue: {e} {e.read()[:200]!r}")
                continue
        log(f"alert: {title}" + (f" → {url}" if url else " (printed only: not running on GitHub)"))
        conn.execute("INSERT INTO alerts_log (ts, kind, key, title, url) VALUES (?,?,?,?,?)",
                     (iso(now()), a["kind"], a["key"], title, url))
    conn.commit()
    return sent
