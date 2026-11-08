# Ledger: Roblox Trend Tracker
_Updated 2026-11-08 04:52 by Claude Code (Opus 5.5)_ · **Status:** idle

## Goal
Collect daily data on Roblox games (charts + lineage-style search terms), including the flops, so we can spot breakouts early, measure base rates, and later backtest/grade predictions about which concepts reach 1M+ CCU.

## Constraints
- Python 3 stdlib only (no pip installs); SQLite database in data/ (gitignored).
- Only public, unauthenticated Roblox web endpoints; polite request rate; generic User-Agent.
- Not a game: touches no Roblox Studio, holds no studio-lock.

## Key Decisions
- Project lives at ~/development/Roblox Dev/tracker (user's pick).
- Data sources: explore-api get-sorts (26 charts x phone+computer), omni-search (config queries, 3 pages each), games API (50/batch), votes (100/batch). Search is where the flops come from.
- First run's events are flagged baseline=1 so they never alert.
- Schema version lives in PRAGMA user_version; opening the DB is read-only when current.

## State
- Done: repo initialised; API probe; collector (tracker/api.py, db.py, config.py, collect.py, config.toml). Test run: 4,029 games, ~6 min (429s on games API, now paced per host).
- Done: report (md+html), prediction log + grading, notifications, CLI, unit tests (7 pass).
- Done: LaunchAgent installed (user approved): ~/Library/LaunchAgents/local.roblox-trend-tracker.plist, every 3h at :07. Fixed DB locking (collector commits before network phase; connect() no longer writes).
- Done: first real collection OK (run 1: 4,031 games, 249 requests, 456s, 5.5 MB DB); report checked via latest.md (HTML not viewed: browser pane can't open file://).
- Now: nothing running; schedule takes over.
- Next: check the first scheduled run (06:07) in logs/run.log; after 2 days growth columns fill in.

## In flight
- none

## Open Questions
- none

## Log
- 2026-11-08 04:52 Claude Code: first real run verified; clearer base-rate labels; README storage estimate corrected.
- 2026-11-08 04:47 Claude Code: schedule installed; DB lock fix; stale 'running' runs marked abandoned.
- 2026-11-08 04:43 Claude Code: report, predictions, notify, CLI, tests, schedule scripts, README.
- 2026-11-08 04:37 Claude Code: collector + schema + config; first test run OK.
- 2026-11-08 04:30 Claude Code: git init, .gitignore, ledger.
