# Roblox Trend Tracker

Logs Roblox's charts and genre search results every 3 hours into a local database, so you can:

- **spot breakouts early**: new games climbing fast, and new loops worth borrowing, within days;
- **see the flops, not just the winners**: search pulls in hundreds of small clones per theme;
- **measure base rates**: of the games launched in this genre, how many reach 1K / 10K / 100K / 1M players;
- **keep score on predictions**: write down a prediction before launch, and the tracker grades it.

Not a game: it never touches Roblox Studio and needs no studio-lock.

## Where to look

- `reports/latest.html`: the main report, with icons; open it in a browser. `reports/latest.md` holds the same tables in Markdown.
- `reports/daily/YYYY-MM-DD.html`: one report per day, kept as an archive.
- `logs/run.log`: what each scheduled run did.
- macOS notifications when a game under 60 days old crosses 10K, 100K or 1M players.

Report sections: breakouts · milestones in the last 24h · your games · this genre's games under 90 days old · lineage reference games · base rates · prediction log · top 25 overall.

## Commands

```bash
python3 -m tracker run                 # collect now + report (what the schedule runs)
python3 -m tracker report              # rebuild the report without collecting
python3 -m tracker status              # recent runs, errors, database size
python3 -m tracker find "steal"        # search the database (add --online to search Roblox)
python3 -m tracker game "Steal An Egg" # one game: daily peaks, milestones, labels
python3 -m tracker watch add 1234567 --kind mine --note "my new game"
python3 -m tracker watch add place:137745762163774 --kind mine   # by place id
python3 -m tracker watch list
python3 -m tracker export              # every game to reports/games.csv
```

### Prediction log

Write the prediction **before** the numbers come in, then let the tracker grade it.

```bash
# An existing game: "60% chance it peaks at 5K+ players by Nov 22"
python3 -m tracker predict add --game "grow food for animals" --peak 5000 --by 2026-11-22 --prob 0.6

# A concept you haven't published yet: "30% chance of 10K+ in its first 14 days"
python3 -m tracker predict add --subject "Concept: net the herd" --peak 10000 --within-days 14 --prob 0.3
# ...after publishing it, link the prediction to the game:
python3 -m tracker predict link 2 --game 1234567890

python3 -m tracker predict list
```

The report shows the hit rate, the Brier score (0 is perfect, 0.25 is coin-flipping) and calibration: whether your "30%" calls come true about 30% of the time.

### Lineage labels

Code games by loop stage so lineage theories can be checked against the data later:

```bash
python3 -m tracker label "Steal An Egg" stage.capability=treadmill stage.trip=run-out-and-back stage.prize=egg-hatch stage.earn=base-income stage.conflict=steal
python3 -m tracker label list stage.capability
```

## Schedule

```bash
scripts/install_schedule.sh     # LaunchAgent: every 3 hours at :07; one catch-up run on wake
scripts/uninstall_schedule.sh   # removes it (refuses while a run is in progress)
```

## Settings

`config.toml` holds the search queries, chart devices, alert thresholds and the watchlist (your games and the lineage games). Every run re-reads it.

## Caveats

- These are **undocumented public Roblox endpoints**, so they can change or break. Check `python3 -m tracker status` if a report looks stale.
- Player counts are sampled every 3 hours, so the true peak can fall between samples.
- The database only contains games that appeared in a chart or a search result at least once. Games with no visibility at all are invisible, so base rates mean "games that got noticed at all".
- Base rates are only honest for games **launched after tracking began**, because older games were already past their peak. That column fills in over weeks.
- `data/tracker.sqlite` is the irreplaceable part, and it isn't in git. Back it up with Time Machine or similar. The first run made a 5.5 MB database; expect a few MB of growth per run, so a few GB a year.

## Files

```
tracker/api.py       Roblox endpoints (paced, retries on 429)
tracker/collect.py   one collection run → snapshots, chart/search hits, milestone events
tracker/report.py    Markdown + HTML report
tracker/predict.py   prediction log and grading
tracker/notify.py    macOS notifications
tracker/db.py        SQLite schema
config.toml          settings + watchlist
scripts/             schedule install/uninstall, run wrapper
```
