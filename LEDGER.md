# Ledger: Roblox Trend Tracker
_Updated 2026-11-08 05:30 by Claude Code (Opus 5.5)_ · **Status:** working

## Goal
Wave radar (2026-11-08): spot Roblox waves as they start (Just starting → Jump in now → Crowded → Fading) and show opportunities on a dashboard, running on GitHub Actions (user chose GitHub; nothing runs on their Mac).

Original goal: Collect daily data on Roblox games (charts + lineage-style search terms), including the flops, so we can spot breakouts early, measure base rates, and later backtest/grade predictions about which concepts reach 1M+ CCU.

## Constraints
- Python 3 stdlib only (no pip installs); SQLite database in data/ (gitignored).
- Only public, unauthenticated Roblox web endpoints; polite request rate; generic User-Agent.
- Not a game: touches no Roblox Studio, holds no studio-lock.

## Key Decisions
- Radar runs on GitHub Actions in a private repo (user's choice 2026-11-08); dashboard = README of the `radar` branch; alerts = GitHub issues labelled wave-alert.
- Project lives at ~/development/Roblox Dev/tracker (user's pick; it's fine there, though it isn't a game).
- No automatic runs: user said 2026-11-08 this shouldn't run on their computer.
- Data sources: explore-api get-sorts (26 charts x phone+computer), omni-search (config queries, 3 pages each), games API (50/batch), votes (100/batch). Search is where the flops come from.
- First run's events are flagged baseline=1 so they never alert.
- Schema version lives in PRAGMA user_version; opening the DB is read-only when current.

## State
- Done: repo initialised; API probe; collector (tracker/api.py, db.py, config.py, collect.py, config.toml). Test run: 4,029 games, ~6 min (429s on games API, now paced per host).
- Done: report (md+html), prediction log + grading, notifications, CLI, unit tests (7 pass).
- Done: LaunchAgent installed, then removed at the user's request (they don't want a program running on their Mac); plist in ~/.Trash. Runs are manual only now. Fixed DB locking (collector commits before network phase; connect() no longer writes).
- Done: first real collection OK (run 1: 4,031 games, 249 requests, 456s, 5.5 MB DB); report checked via latest.md (HTML not viewed: browser pane can't open file://).
- Done: first run of the concept-selection system → analysis/2026-11-08-shortlist.md (top pick: ragdoll fling-yourself + Throw Food loop).
- Done: radar engine (tracker/waves.py), dashboard (tracker/dashboard.py → reports/DASHBOARD.md + waves.json), GitHub-issue alerts (tracker/alerts.py), `radar` CLI command, hybrid collector (listing counts + limited details calls), daily table + pruning (schema v2), 13 tests pass.
- Done: workflow .github/workflows/radar.yml (every 3h, dashboard+gzipped DB force-pushed to `radar` branch), README rewritten for the radar. Wave rules fixed: novelty ignores dead old games; crowded = copies failing (overall or newest), not raw count; small hot pockets inside a crowded wave shown separately. Hybrid collector run: 2.5 min.
- Now: create private repo (gg import roblox-wave-radar), trigger first cloud run, check it.
- Next: user decides on a concept; recheck the ragdoll wave in 1–2 days with a manual run. Manual snapshot: python3 -m tracker run. Don't reinstall the schedule unless the user asks.

## In flight
- none

## Open Questions
- none

## Log
- 2026-11-08 05:40 Claude Code: workflow + README; wave rules fixed after deeper search exposed flaws.
- 2026-11-08 05:30 Claude Code: wave radar engine, dashboard, alerts, tests.
- 2026-11-08 05:20 Claude Code: ran the concept system on the snapshot; shortlist saved in analysis/.
- 2026-11-08 04:58 Claude Code: schedule removed at user's request; README says runs are manual.
- 2026-11-08 04:52 Claude Code: first real run verified; clearer base-rate labels; README storage estimate corrected.
- 2026-11-08 04:47 Claude Code: schedule installed; DB lock fix; stale 'running' runs marked abandoned.
- 2026-11-08 04:43 Claude Code: report, predictions, notify, CLI, tests, schedule scripts, README.
- 2026-11-08 04:37 Claude Code: collector + schema + config; first test run OK.
- 2026-11-08 04:30 Claude Code: git init, .gitignore, ledger.
