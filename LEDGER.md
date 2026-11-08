# Ledger: Roblox Trend Tracker
_Updated 2026-11-08 05:00 by Claude Code (Opus 5.5)_ · **Status:** working

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

## State
- Done: repo initialised; API probe; collector (tracker/api.py, db.py, config.py, collect.py, config.toml). Test run: 4,029 games, ~6 min (429s on games API, now paced per host).
- Now: report (tracker/report.py), predictions, CLI (tracker/__main__.py).
- Next: launchd schedule (scripts/), README, end-to-end test.

## In flight
- none

## Open Questions
- none

## Log
- 2026-11-08 05:00 Claude Code: collector + schema + config; first test run OK.
- 2026-11-08 04:30 Claude Code: git init, .gitignore, ledger.
