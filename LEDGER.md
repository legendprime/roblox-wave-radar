# Ledger: Roblox Trend Tracker
_Updated 2026-11-08 04:30 by Claude Code (Opus 5.5)_ · **Status:** working

## Goal
Collect daily data on Roblox games (charts + lineage-style search terms), including the flops, so we can spot breakouts early, measure base rates, and later backtest/grade predictions about which concepts reach 1M+ CCU.

## Constraints
- Python 3 stdlib only (no pip installs); SQLite database in data/ (gitignored).
- Only public, unauthenticated Roblox web endpoints; polite request rate; generic User-Agent.
- Not a game: touches no Roblox Studio, holds no studio-lock.

## Key Decisions
- Project lives at ~/development/Roblox Dev/tracker (user's pick).

## State
- Done: repo initialised.
- Now: probing Roblox explore/search/games APIs.
- Next: write collector (tracker/collect.py) and schema.

## In flight
- none

## Open Questions
- none

## Log
- 2026-11-08 04:30 Claude Code: git init, .gitignore, ledger.
