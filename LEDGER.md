# Ledger: Roblox Trend Tracker
_Updated 2026-11-09 11:10 by Claude Code (Opus 5.5)_ · **Status:** idle

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
- Done: private repo legendprime/roblox-wave-radar created (gg import) and pushed.
- First cloud run (42471596440) was cancelled at the 25-min limit: charts worked from GitHub, then search went silent (suspected silent 65s rate-limit sleeps on shared GitHub IPs). Fix: log rate-limit waits + search progress; time budgets for search (540s) and details (420s); hot-wave queries first; dashboard warns on incomplete checks.
- Second cloud run (42473494375) succeeded but search was throttled to ~1 request/min from GitHub (4/38 searches), so it saw mostly winners and sent 4 wrong Jump-in alerts (evolution, animals, roadster, ride); closed as issues #2-5 with a correction note. #1 ragdoll is right.
- Fix: search rotation (hot-wave words first, fixed list continues via meta.search_cursor), phone-only charts, 2 pages; alert gate (>=3 checks, >=3000 games, stage held 2 checks; schema v3 wave_state.stage_runs); dashboard notes search coverage. Cloud DB seeded with local full-search data (4,774 games, runs 1-2) on the radar branch.
- Third cloud run (42474861557) OK: 44/44 searches in 41s (throttling varies by runner IP), 4,436 games snapshot, 220 new, no alerts (gate working), dashboard live at github.com/legendprime/roblox-wave-radar/tree/radar. Jump in now: ragdoll, malam.
- Website (user asked for an app, chose a self-updating public website): tracker/site.py builds site/index.html (data inlined, no external libs) each run; workflow deploys it with GitHub Pages (upload-pages-artifact@v3 + deploy-pages@v4, environment github-pages). Repo must go public on free GitHub (user accepted); commit email legendprim3@gmail.com is already public via their demoapp repo.
- Done: repo made public (gh repo edit --accept-visibility-change-consequences; gg visibility lacks that flag), Pages enabled (build_type=workflow). Run 42475925907 published the site; checked in the browser pane: tabs, cards, icons, expand list, lone breakouts, search filter, no console errors.
- Done (all 6 improvement groups, user said 'build all'): schema v4 (badges, badge_fetch, creators, updates, wave_days, copy_stage); tracker/enrich.py (badges daily + creators weekly for ~170 key games, 150s budget, most important first); tracker/insights.py (mechanics from keywords, stand-ins: visits/player from top badge, minutes/visit, like %, favs/1K, update rhythm; winners vs flops; opportunity score; rising; chart entries; your games; track record + timelines; wave-forming alerts); site rebuilt with Top opportunities, Your games, 9 tabs. 17 tests pass; all tabs render in a Node DOM smoke test. Grouping stays title-based (description grouping too noisy); descriptions feed mechanics instead.
- Cloud run 42480677973 OK (17 min, throttled search 5/44, badges 167 games, 8 creators); new site checked in the browser pane (opportunities, your games, tabs, wave card facts, winners vs flops, mechanics table). Follow-up fixes: retry missing icons after 6h, big-studio share shown only when creators cover >=50% of players, 'just starting' alerts need >=1 successful copy (issue #9 'riders' went out before this rule), workflow timeout 30 min.
- Done: ragdoll concept brainstorm → analysis/2026-11-08-ragdoll-concepts.md (1. Build a Ragdoll 14/16, 2. Steal a Ragdoll 12/16, 3. Ragdoll Hospital 11/16).
- Done: Grow Food For Animals review → analysis/2026-11-09-grow-food-for-animals.md (same concept flopped twice: Launch Food For Animals, Bait an Animal; title reads as Throw Food; plan: size is the prize, new name, rares go to the best garden, simpler first 10 min, ship in ~2 weeks; night stealing is the user's call). Implementation belongs in the game's own folder.
- Now: nothing running locally; cloud radar + site every 3h at :17 UTC.
- Next: after ~24h check Rising fastest / visits-per-day fill in; after ~14 days read the Track record tab and tune [radar] thresholds from it; creators fill in over ~1 day.

## In flight
- none

## Open Questions
- none

## Log
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
