# Roblox Wave Radar

Spots Roblox **waves** (groups of new games built on the same idea) as they start, and tells you which ones are open to jump into, so you can get in early, the way the first good Steal An Egg variants did.

It runs **in the cloud on GitHub every 3 hours**. Nothing runs on your computer.

## Where to look

- **The app:** **https://legendprime.github.io/roblox-wave-radar/** is an interactive website rebuilt every 3 hours, on phone and computer. It has:
  - **⭐ Top opportunities:** ranked, with the reasons for each.
  - **🧑‍💻 Your games:** which wave each one is in, and that wave's stage.
  - **Tabs:**
    - 🟢 Jump in now · 🌱 Just starting · 🔴 Crowded
    - 👀 Lone breakouts (🌊 marks one that just got its first lookalikes)
    - 🚀 Rising fastest · 📈 New on charts
    - 🧩 Mechanics: which mechanics show up in games that succeed vs fail
    - 🎯 Track record: does the radar work?
  - **Wave cards:** a 14-day player chart, mechanics, winners vs flops, the share held by big studios, plus the leader's stand-in stats: visits per player (from badges), minutes per visit, like rate, update rhythm, creator size, progress badges and new event badges.
- **Plain-text version:** this repo's [`radar` branch](../../tree/radar) (it opens as that branch's README).
- **Alerts:** a GitHub issue labelled `wave-alert` opens (and GitHub notifies you) when:
  - a wave moves to 🟢 **Jump in now**,
  - a big wave moves to 🌱 **Just starting**, or
  - a game under 3 weeks old crosses 10K players with nothing like it around (a possible new wave).

## What the stages mean

| Stage | Meaning | What to do |
|---|---|---|
| 🌱 Just starting | A young game is breaking out and only a few copies exist | Watch it; start sketching a twist |
| 🟢 Jump in now | Copies with a twist are succeeding and it isn't crowded yet | This is the window: weeks, not months |
| 🔴 Crowded | Lots of copies, copies mostly failing, or the leader is old | Too late for a copy; only a big change has a shot |
| ⚫ Fading | Total players falling | Move on |
| 👀 Lone breakout | A big young game with no wave around it yet | The next wave often starts as one of these |

How a wave is found: the radar groups games made in the last 60 days by shared title words (ragdoll, steal, for animals...). It then measures how fast copies appear, how many copies reach 1K players, whether total players are growing, and how old the leading game is. Every threshold is in `config.toml` under `[radar]`.

The radar tells you **when** a wave is open. The idea and the twist are still yours. A good opening plus a weak twist still flops, and nothing here guarantees a hit.

## Running it

- **Automatically:** `.github/workflows/radar.yml`, every 3 hours.
- **Extra check now:** GitHub → Actions → Wave radar → Run workflow.
- **Turn it off:** GitHub → Actions → Wave radar → ⋯ → Disable workflow.
- **Cost:** free. A private repo gets 2,000 free Actions minutes a month; each run takes a few minutes. The Actions tab shows real usage.

Locally (optional, nothing installs itself):

```bash
python3 -m tracker radar --no-alerts   # one check + reports/DASHBOARD.md
python3 -m tracker game "Ragdoll Physics"
python3 -m tracker find "ragdoll" --online
```

To look at the cloud data locally, download `data/tracker.sqlite.gz` from the `radar` branch, unzip it into `data/tracker.sqlite`, then use the commands above.

## Other tools in here

- **Prediction log:** write a guess before launching, and the radar grades it. `python3 -m tracker predict add --help`
- **Watchlist:** your games and the lineage reference games live in `config.toml` `[[watch]]`.
- **Labels:** code games by loop stage for lineage analysis. `python3 -m tracker label --help`
- **HTML report:** the older all-in-one report. `python3 -m tracker run` (writes `reports/latest.html`).
- **analysis/:** written analyses, e.g. the first next-game shortlist.

## Caveats

- These are **undocumented public Roblox endpoints**, so they can change. If the dashboard stops updating, check the Actions tab for a failed run.
- The radar only sees games that show up in Roblox's charts or search. To find the small copies too, it adds each hot wave's words to its next searches.
- Player counts are sampled every 3 hours, so a true peak can fall between samples.
- Growth and trend numbers need a day or more of history before they appear.
- Grouping by title words is rough. Unrelated games that share a word can land together, and a wave whose games all have different names is only caught as lone breakouts.

## Files

```
tracker/collect.py    one collection: charts + search + details for games that need them
tracker/waves.py      groups games into waves, stages them, picks alerts
tracker/dashboard.py  DASHBOARD.md + waves.json
tracker/alerts.py     GitHub issue alerts
tracker/db.py         SQLite schema (raw snapshots kept ~8 days, daily peaks forever)
config.toml           search words, thresholds, watchlist
.github/workflows/    the every-3-hours cloud run
scripts/              optional Mac schedule (not installed)
```
