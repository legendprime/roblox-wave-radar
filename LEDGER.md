# Ledger: Roblox Trend Tracker
_Updated 2026-11-23 10:45 by Claude Code (Fable 5.2)_ · **Status:** idle

## Goal
Money first (user, 2026-11-23): the aim is maximum revenue for the least build time, not player count. The radar should show which small, quickly built games earn, what they sell, and whether an idea is already taken.

Wave radar (2026-11-08): spot Roblox waves as they start (Just starting → Jump in now → Crowded → Fading) and show opportunities on a dashboard, running on GitHub Actions (user chose GitHub; nothing runs on their Mac).

## Constraints
- Python 3 stdlib only (no pip installs); SQLite database in data/ (gitignored).
- Only public, unauthenticated Roblox web endpoints; polite request rate; generic User-Agent.
- Not a game: touches no Roblox Studio, holds no studio-lock.
- The repo and website are public: the user's own game ideas never go in git. `ideas.toml`, `reports/ideas.md` and `analysis/private/` are ignored and exist only on this Mac.

## Key Decisions
- Radar runs on GitHub Actions in a private repo (user's choice 2026-11-08); dashboard = README of the `radar` branch; alerts = GitHub issues labelled wave-alert.
- Project lives at ~/development/Roblox Dev/tracker (user's pick; it's fine there, though it isn't a game).
- No automatic runs: user said 2026-11-08 this shouldn't run on their computer.
- Data sources: explore-api get-sorts (26 charts x phone+computer), omni-search (config queries, 3 pages each), games API (50/batch), votes (100/batch). Search is where the flops come from.
- First run's events are flagged baseline=1 so they never alert.
- Schema version lives in PRAGMA user_version; opening the DB is read-only when current.
- Revenue stand-in (2026-11-23): Roblox's Top Earning chart order vs players. "× the usual money per player" = median players of the 7 chart neighbours either side ÷ the game's players. Stores (passes + paid products with prices) are public and read weekly.
- Idea check runs only by hand on this Mac (`python3 -m tracker ideas`), because results would be public anywhere else.

## State
- Done (2026-11-08/09, details in git log): collector, SQLite (now schema v5), wave radar, dashboard, GitHub-issue alerts, public website on GitHub Pages, insights (mechanics, stand-ins, track record), three analyses in analysis/.
- Done (2026-11-23): Money view. tracker/money.py (earning power, young/small earners, by type, store summaries, 💰 alert when a game under 60 days old first reaches Top Earning); chart_days table keeps daily Top Earning positions forever; stores via enrich.run_store (75s budget, weekly refresh); website 💰 Money tab + dashboard section; search words added for shop sims / card opening / playground / "be a". 23 tests pass.
- Done (2026-11-23): private idea check, tracker/ideas.py + `ideas` command (verdicts: open untried / tried none took off / being tried / taken; flags games that appeared since the last check). ideas.example.toml is committed; the real list (55 ideas) is in ideas.toml, local only.
- Verified 2026-11-23: full local run against a copy of the cloud database (v4 → v5 migration, 92 stores read in 75s, 31 young games on the earning chart); Money tab checked in the browser at desktop and phone width, no console errors.
- Written for the user (local only, private): analysis/private/2026-11-23-what-to-build-next.md.
- Now: nothing running locally; cloud radar + site every 3h at :17 UTC (runs take ~20 min of the 30 min limit; the store step adds up to 75s).
- Next: after the next cloud run, check the Actions log for the "stores:" line and open the site's Money tab (legendprime.github.io/roblox-wave-radar/#money). If the run nears 25 min, lower `store_budget_s` in config.toml [enrich]. Rerun `python3 -m tracker ideas` before starting any build.

## In flight
- none

## Open Questions
- none

## Log
- 2026-11-23 10:45 Claude Code: Money view (Top Earning vs players, stores, alert), private idea check, private what-to-build analysis.
- 2026-11-09 11:10 Claude Code: Grow Food For Animals breakout review (analysis/2026-11-09-grow-food-for-animals.md).
- 2026-11-08 08:05 Claude Code: ragdoll concepts (analysis/2026-11-08-ragdoll-concepts.md); top pick Build a Ragdoll.
- 2026-11-08 07:55 Claude Code: live site verified; icon retry, big-share coverage, starting-alert rule.
- 2026-11-08 07:35 Claude Code: insights, enrichment, track record, new site sections.
- 2026-11-08 06:50 Claude Code: website live at legendprime.github.io/roblox-wave-radar, verified.
- 2026-11-08 06:30 Claude Code: interactive website + Pages deploy step.
- 2026-11-08 06:25 Claude Code: third cloud run verified; radar live.
- 2026-11-08 06:20 Claude Code: search rotation + alert gate; seeded cloud DB; closed 4 wrong alerts.
- 2026-11-08 06:00 Claude Code: first cloud run timed out; added logging + time budgets.
- 2026-11-08 05:40 Claude Code: workflow + README; wave rules fixed after deeper search exposed flaws.
- 2026-11-08 05:30 Claude Code: wave radar engine, dashboard, alerts, tests.
- 2026-11-08 05:20 Claude Code: ran the concept system on the snapshot; shortlist saved in analysis/.
- 2026-11-08 04:58 Claude Code: schedule removed at user's request; README says runs are manual.
- 2026-11-08 04:52 Claude Code: first real run verified; clearer base-rate labels; README storage estimate corrected.
- 2026-11-08 04:47 Claude Code: schedule installed; DB lock fix; stale 'running' runs marked abandoned.
- 2026-11-08 04:43 Claude Code: report, predictions, notify, CLI, tests, schedule scripts, README.
- 2026-11-08 04:37 Claude Code: collector + schema + config; first test run OK.
- 2026-11-08 04:30 Claude Code: git init, .gitignore, ledger.
