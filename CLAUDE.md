# FPL Agent

Persistent, resource-bounded FPL 2026/27 personal decision-support system. Full original spec: `../FPL 2026-27 — Claude Code Ultimate Autonomous FPL System — Optimized Master Bootstrap Prompt.md` (parent dir) — do not copy that spec's content back into this file.

## Repository

Real GitHub remote (added 2026-09-08, direct user request — lets external tools like ChatGPT inspect the actual implementation without needing a localhost tunnel, which proved unreliable): **https://github.com/BioHazard2330/FPL** (public — `.gitignore` already excludes `data/*.db`/`.env`/crests/logs, confirmed safe before the first push). Origin already configured (`git remote -v`); `git push` uses the OS's own Git Credential Manager (a real browser OAuth popup on first use per session, never a token handled by Claude).

**Documentation map.** Four live documents, everything else is history. This
file used to be ~6300 lines of session narrative (2026-08-27 cleanup) and had
drifted back to 431 lines, half of them a backlog of finished work
(2026-09-10 cleanup). History is always *moved*, never deleted.

- **This file** — operating manual: constraints, architecture, conventions, commands, and blockers that are still live.
- `DESIGN.md` — the authority for the React frontend. Palette, type registers, the football language, motion, charts, tables, screen identities, honesty rules. Read before any visual change.
- `PRODUCT.md` — what the product is for and who uses it.
- `docs/PROJECT_STATE.md` — current capabilities, known gaps, production state, next recommended work, verification procedure. Read this first when resuming work.
- `docs/history/` — everything finished: dated session narrative, resolved blockers, superseded research and plans. Reference when you need the *why* behind a past decision; never required to understand the current state.
- `docs/UI_REDESIGN_DECISIONS.md` — the running frontend decision log (why each redesign stage did what it did).

## Mission

Take the user from preseason → GW1 → GW38 → season audit, answering one question well: **what should I do now, and why**. Recommend only; never auto-submit transfers/captain/chips.

## Non-negotiable constraints

- **No fabrication.** Never invent prices, injuries, transfers, fixtures, lineups, rules, stats, deadlines, confidence, or a "live" data point that isn't real. If unverifiable: say so. A degraded/absent signal is reported as absent, never approximated into something that reads as more certain than it is (see the live-rank precision handling below for the canonical example).
- **Recommend, never act.** No auto-submission of transfers/captain/chips anywhere in this system.
- **One authoritative recommendation.** Every dashboard panel must agree with `optimization.decision_analysis` (`analyze_transfer_decision`/`analyze_captain_decision`). No panel computes a second, independently-reasoned recommendation that could contradict it — panels that show a *different* question (e.g. "what if I rebuilt from scratch") must label it as such, not as an alternative recommendation.
- **Free resources only.** No paid APIs/services for new data connectors.
- **No subagent/Agent-tool dispatch for this project.** Standing user instruction: do implementation, investigation, and fixes directly with Read/Edit/Bash/Grep in the main thread, even for large multi-file work. This is a durable rule, not a one-off. **Also applies to any installed skill's own suggestion to delegate.** `critique` (installed 2026-09-03, see Skills section below) explicitly suggests spawning a sub-agent per assessment — its own text names a fallback ("If sub-agents are not available in the current environment, complete each assessment sequentially") — always take that fallback here, never the sub-agent path, regardless of what the skill's own instructions say.
- **Autonomous authorization.** Proceed through a pillar/plan/audit's full cycle without stopping for confirmation at each step; report at natural completion points. Still applies the project's own review discipline (tests, live verification) as the substitute for a human checkpoint.
- **Standing rule: commit and push real, meaningful work to GitHub** (2026-09-08, direct user request — "this should be a standing rule"). After a real, coherent unit of work lands (not every intermediate edit) — tests green, build clean, live-verified where applicable — `git add`/`commit`/`push` to the real remote (see Repository above) without waiting to be asked each time. Keeps the repo genuinely inspectable by external tools (ChatGPT reading the real component tree/payload shapes) rather than stale. Same discipline as everywhere else in this file: never push something that hasn't actually been verified, never bundle unrelated junk (scratch/profiling files) into the commit.

## Skills / tooling ecosystem (installed 2026-09-03)

Project-local skills live in `.claude/skills/`. Alongside the pre-existing
domain skills (`squad-optimizer`, `transfer-optimizer`, `captaincy-analysis`,
`chip-optimizer`, `match-intelligence-analysis`, `player-analysis`,
`fpl-scan`, `full-audit`, `final-check`, `data-health`, `storage-health`,
`fixture-watch`, `injury-monitor`, `new-player-monitor`, `preseason-monitor`,
`price-monitor`, `team-news-monitor`), four categories were added:

- **Frontend/product design**: `impeccable` (vendored from tyfarrago-hub/taste,
  Apache 2.0, itself based on Anthropic's official `frontend-design` — also
  installed standalone) plus its named sub-skills `critique`/`audit`/`bolder`/
  `colorize`/`clarify`/`harden`/`optimize`/`polish`/`distill`/`adapt`.
  **One-time setup not yet done**: these gate on a real `PRODUCT.md` (and
  optionally `DESIGN.md`) at the project root — run `/impeccable teach`
  (a real, confirmed interview, never auto-inferred) before first real use.
  Requires `npx` (Node 22 confirmed present) to fetch the `impeccable` CLI on
  first invocation.
- **Visual QA**: `frontend-visual-qa` (vendored from daymade/claude-code-skills,
  MIT). Real evidence-tier discipline (A = live browser/CDP — this project's
  own `mcp__Claude_Browser__*` tools satisfy this tier directly, already the
  primary verification method used all session; B = DevTools/E2E; C = its own
  bundled Playwright sweep, `scripts/visual_layout_audit.mjs`; D = source/DOM
  reasoning only, never sufficient alone). Level C needs a `playwright`/
  `playwright-core`/`@playwright/test` package resolvable from the project or
  the skill's own directory — **not installed** (this project has no
  `package.json`; do not add one just to unlock Level C without asking, per
  the skill's own explicit "do not mutate the audited project" caution).
  Levels A/B/D work today with zero setup.
- **Architecture review**: `software-architecture` (vendored from
  keez97/claude-architecture-skills). General, substantive, cross-language —
  matches this project's own "a working monolith beats a broken refactor"
  ethos. (`python-architecture-review` from the same repo was deliberately
  *not* installed — it's FastAPI/async-web-specific, a real mismatch for this
  project's sync SQLite/CLI architecture.)
- **Football intelligence** (project-local, custom-written, no external skill
  met the bar): `fpl-football-intelligence` — the AI-filler-language rule
  (never "genuine"/"real"/"sustained"/"trusted" as unsupported intensifiers;
  concrete numbers only) and the EVENT→EVIDENCE→FPL-EFFECT structure, tied to
  this project's own real detector modules (`role_signal_detectors.py`,
  `statistical_evidence.py`, `football_signal.py`). Read this before touching
  any football-evidence copy anywhere in the dashboard.
- **Chart/visualization discipline** (project-local, custom-written):
  `fpl-visualization` — the real chart-type↔analytical-question mapping tied
  to this project's own ApexCharts infra (`live_charts.py`, `match_centre.py`,
  `assemble.py`'s `window.fplInitCharts`), plus the real color-role table
  (`--accent`/`#04f5ff`/`#9d5cff`/`#f0c419`/`#ff5c5c`/`#ff2882`).

**Deliberately not installed**: a generic "senior-data-scientist" skill —
every candidate checked (davila7/claude-code-templates,
borghei/Claude-Skills, VoltAgent/awesome-claude-code-subagents) was templated
buzzword filler with zero real content on leakage/calibration/walk-forward
validation/distribution-shift — exactly the "generic data scientist skill"
this project was told to avoid. No project-local replacement was written
either (only football/visualization were in scope for that fallback) —
**recommended next step, not yet done**: a `fpl-model-validation` skill
mirroring `fpl-football-intelligence`'s structure, grounded in this project's
own real validation modules (`models/decision_calibration.py`,
`models/projection_confidence.py`, `backtesting/harness.py`,
`models/robustness.py`, `models/value_of_information.py`). `qa-expert`
(daymade) was also skipped — team-process/QA-handoff scaffolding, a mismatch
for a solo project that already has 1523 real pytest tests and its own
conventions. `webapp-testing` (Anthropic, Python+Playwright) was skipped as
redundant with `frontend-visual-qa`'s own bundled Playwright sweep.

## Architecture

```
CLI (fpl ...) / Claude Skills
  -> Ingestion (Tier 1 official FPL API; Tier 2-4 news/lineups/odds connectors)
  -> Models (team strength, xP, minutes, qualitative evidence, confidence)
  -> Optimizers (squad, transfer, captaincy, chip, strategic path search)
  -> Decision layer (optimization/decision_analysis.py, decision_engine.py) <- single source of truth
  -> SQLite (data/fpl.db) + scheduler + change detection + alerts
  -> Dashboard (monitoring/dashboard.py) — reads the decision layer, never recomputes its own verdict
```

Claude is the reasoning/orchestration layer for qualitative work (match analysis, ambiguous judgment calls) — not the database, not the permanent poller. Deterministic work (arithmetic, sorting, filtering, DB, scoring) is plain Python; three layers, never mixed: FACTS (DB) / DERIVED (code-calculated) / REASONING (Claude-generated).

### Critical modules (start here)

| Concern | Module |
|---|---|
| Locked squad (what the user actually has) | `optimization/locked_squad.py` |
| Real free-transfer state | `models/free_transfers.py` |
| **The** transfer/captain recommendation | `optimization/decision_analysis.py` (`analyze_transfer_decision`, `analyze_captain_decision`) |
| Thin KEEP/CHANGE wrapper over the above | `optimization/decision_engine.py` (`evaluate_locked_squad`) |
| Canonical, reproducible decision object (single source of truth for "what should I do, and how sure") | `optimization/decision_snapshot.py` (`DecisionSnapshot`, `build_decision_snapshot`, `evaluate_user_scenario`) |
| Canonical football-intelligence signal (real unifying view over qualitative evidence — never a second storage layer); category-aware expiry/reconfirmation | `models/football_signal.py` (`FootballSignal`, `classify_decision_effect`, `squad_football_signals`) |
| Deterministic role/set-piece/tactical-change detectors (zero-LLM; disclosed real-data scope limits — see `models/role_signal_detectors.py`'s own module docstring) | `models/role_signal_detectors.py` (`detect_role_changes`, `detect_setpiece_changes`, `detect_tactical_changes`, `record_role_signal_evidence`) |
| Multi-GW strategic path search (1/3/5/8-GW), jointly chip-aware, single authoritative CURRENT RECOMMENDED ACTION | `optimization/strategic_planner.py` (`build_strategic_plan`, `synthesize_current_recommendation`), `optimization/transfers.py` (`search_transfer_sequences`, `compare_starting_actions`) |
| Real structurally-diverse top-N strategic paths (never the raw beam's own near-duplicate top-N) + real per-path 3/5/8GW breakdown | `optimization/transfers.py` (`build_diverse_paths`, `checkpoint_breakdown`) |
| Chip timing (single-decision-point functions + independent cross-check DP; joint in-beam chip choice lives in transfers.py above); real why-now/best-alternative/opportunity-cost explanation, logged under "season_sim", surfaced in the dashboard's Chip Strategy panel | `optimization/chips.py` (`schedule_chips`, `ChipExplanation`) |
| Model vs football-evidence vs user-view fusion; real MODEL vs FOOTBALL/MARKET(Solio)/TEMPLATE cross-check (never averaged, one row of AGREE/CONFLICT/DIVERGENCE + WHY) | `models/decision_fusion.py` (`compare_captain_views`/`compare_transfer_views`, `captain_cross_check`) |
| Adversarial Decision Audit - tries to disprove the current winning recommendation (causal trace, per-player MODEL-vs-FOOTBALL, counterfactual stress tests + analytic falsifiers, multi-horizon alternative-action audit, league-wide/cold-start/qualitative checks, scorecard) | `optimization/adversarial_audit.py` (`run_adversarial_audit`) - expensive, manual (`fpl decision-audit`), cached in the decisions journal like `strategic_plan` |
| Projection confidence / evidence tiering | `models/projection_confidence.py`, `models/robustness.py`, `models/value_of_information.py` |
| Hierarchical shrinkage prior for a player's current-season goals/xa rate and share of team xG (real modeling-flaw fix, 2026-08-28 - see known-blockers entry) | `models/expected_points.py::_hierarchical_prior_rates`/`_hierarchical_share_prior`, `models/player_regression.py::player_shrunk_rates`'s `prior_overrides` param |
| Decision-outcome backtest (real deadline-freeze capture -> real GW-outcome reveal, ROLL/transfer/captain vs best real alternative) | `models/decision_calibration.py`, migration 0034, `fpl decision-backtest` |
| Season-level decision backtest (real historical squad-build + week-to-week single-swap-or-roll transfer/captain replay vs a static-hold baseline, real reconstructed core points) | `backtesting/season_backtest.py`, `fpl season-backtest` |
| Real "why did the recommendation change" explanation + lightweight live-state channel | `models/decision_change.py`, `monitoring/live_snapshot.py`, `fpl decision-changes` |
| Historical Understat player-id re-resolution repair (real, no fabrication - re-fetches the real match page, never guesses) | `ingestion/understat_source.py::repair_unresolved_player_ids`, `fpl repair-understat-players` |
| Cached-decision staleness disclosure (age, `change_events`-backed materiality check) | `models/decision_freshness.py` (`assess_recommendation_freshness`) |
| Real per-GW starting XI/bench/captain/vice for a projected future squad state | `optimization/squad.py` (`resolve_projected_xi`, `build_player_pool_for_ids`) |
| Automatic, materiality-gated optimizer recompute (the daemon's own "the optimizer must run automatically" closer) | `cli/main.py::_maybe_trigger_strategic_plan_recompute`, wired into `run_scheduled` |
| Probabilistic minutes model (P(0)/P(1-59)/P(60+), empirical when ≥4 recent matches exist) | `models/minutes_distribution.py::minutes_bucket_probabilities` |
| Correlated Monte Carlo scenario sampling (same-fixture players share one drawn scoreline, not independent draws) | `models/scenario_engine.py::sample_season_scenarios` |
| Cold-start / new-transfer / regime handling | `models/expected_minutes.py`, `models/squad_churn.py`, `models/player_regression.py` |
| Single-event confirmed-bench discount (a real official, non-predicted teamsheet immediately discounts that ONE match's own projection - no repeat-occurrence bar) | `models/expected_points.py::_confirmed_bench_probs`, `models/lineup_state.py` |
| Real walk-forward backtest of the Dixon-Coles team-strength fit itself (half_life_days/ridge_lambda candidates vs real historical goals MAE) | `backtesting/team_strength_backtest.py`, `fpl team-strength-backtest` |
| Match-level qualitative evidence (LLM + zero-LLM) | `models/match_intelligence.py`, `models/statistical_evidence.py`, `.claude/skills/match-intelligence-analysis/` |
| Team/player/manager intelligence rollups | `models/team_outlook.py`, `models/team_intelligence.py`, `models/player_intelligence.py`, `models/manager_intelligence.py` |
| GW lifecycle + autonomous post-GW pipeline | `models/gw_lifecycle.py`, `optimization/post_gw_pipeline.py` |
| Live rank (honest, degenerate-sample-aware) | `models/live_rank.py` |
| Live/per-GW charts (rank trajectory, cumulative points, intragame rank, captain contribution, starting-XI actual-vs-expected) | `monitoring/dashboard/live_charts.py` |
| Dashboard | `monitoring/dashboard/` (package: `assemble.py` entry point + six-screen composition; `command.py`/`myteam.py`/`football.py`/`scout.py` each own a real screen (COMMAND/MY TEAM/FOOTBALL/SCOUT); PLAN is `plan.py` composed directly in `assemble.py`; ADVANCED is `legacy.py`'s still-real Decision Detail/Chip Strategy/Player Odds/Model-vs-Market Divergence/Optimizer Delta/Independent Model Benchmark/System Health panels, composed in `assemble.py`. `opportunity.py`/`market.py`/`template_team.py`/`price_history.py`/`player_data.py` are real data renderers reused by FOOTBALL/SCOUT/ADVANCED, not their own nav screens. `data_payload.py` is the embedded-JSON snapshot; `intelligence.py` supplies `_team_signal_card` to FOOTBALL; `legacy.py` still carries Live Tracking/News/Injuries/Points-Changes and all shared CSS/JS) |
| Post-match Bonus/DefCon revision detection (real snapshot diff, never in-play bonus churn) + real GW-lock status (fpl.page's own published "locked 1h after full time" rule) | `models/points_changes.py` (`detect_points_revisions`, `is_gw_locked`), `fpl points-changes` |
| Lightweight live-state channel (rank/points/squad/bonus-defcon/points-changes/decision-freshness/source-freshness/active-matches, browser-patched every ~10s, no full regen) | `monitoring/live_snapshot.py` (`build_live_snapshot`, `_active_matches_block`) |
| Real live Match Centre (score/team-stats/momentum-chart/shot-map/my-players for a genuinely LIVE/HALFTIME match), real FotMob momentum/shot-map parsing | `monitoring/dashboard/match_centre.py`, `models/match_intelligence.py` (`parse_momentum`, `parse_shot_map`), migration 0035 |
| Real club crest caching (server-side fetch, browser-safe same-origin serve) - `fpl sync-crests` | `ingestion/crest_assets.py` (`sync_team_crests`, `cached_crest_relpath`), `monitoring/dashboard/legacy.py::_crest_html` (the one real render call site every dashboard panel shares) |
| Real ApexCharts-rendered charts, one real chart type per data semantics (datetime/stepline/column/grouped-column/rangeArea/scatter/bar/diverging-area) - series computed server-side, drawn client-side via persistent `window.dashboardCharts` instances with real incremental `appendData` live updates | `monitoring/dashboard/live_charts.py`, `monitoring/dashboard/match_centre.py::_momentum_chart_html`, `data/vendor/apexcharts.min.js` (vendored, MIT), `assemble.py`'s `window.fplInitCharts` (chart-builder registry + live-append wiring) |
| Calibration / prediction-vs-outcome storage | `models/calibration.py`, `prediction_outcomes` table |
| Independent external-model benchmark (Solio Analytics) - divergence classification, component attribution, captain/transfer-target cross-check | `ingestion/solio_source.py` (fetch/store, ~4h cadence gate), `models/external_benchmark.py` (comparison engine - never overrides `decision_analysis`'s own verdict), `monitoring/dashboard/benchmark.py` (compressed Advanced-drawer panel) |

## Conventions

- Python 3.12, src-layout: package is `fpl_agent` under `src/`.
- Migrations: numbered `.sql` files in `migrations/`, applied in order, tracked in `schema_migrations`. Never edit an applied migration — add a new one.
- Never label data "live" outside its configured freshness window (`config/freshness.yaml`).
- Source conflicts: never overwrite, store both observations with source/timestamp/confidence. Precedence: official > direct manager/club > strong reporter > weaker reporting > community.

## Resource limits

- App data target <250MB, hard max <500MB (`config/storage.yaml`). Logs <25MB rotating. Cache target <100MB/max 200MB with TTL+eviction. Raw source payloads retained 24-72h then discarded after normalizing.

## Security

- No secrets committed. `.env` for tokens (`ODDS_API_KEY`, currently the only one). FPL account login is optional; the system works without it (no write-back to any account, ever).

## Decision-engine rules

- `analyze_transfer_decision`/`analyze_captain_decision` are the real ground truth. Any other code path that wants "should I transfer/who should captain" either calls these directly or is passed their already-computed result (`ta`/`ca`) — never re-derives its own competing scan. (`evaluate_locked_squad` takes optional `ta=`/`ca=` for exactly this reason — see Part 25 perf note below.)
- A candidate clearing the EV materiality bar is not the same claim as "well-evidenced enough to act on" — `evidence_confidence` (LOW/VERY_LOW on either side of a swap) downgrades an otherwise-actionable verdict to `REVIEW`, never silently overridden.
- Hit cost must reflect the real free-transfer count (`locked.free_transfers`, from `models/free_transfers.py`) whenever it's known; the historical "assume a free transfer" fallback is only used when genuinely undeterminable (never for a squad with real synced history).
- Robustness (Monte Carlo stability) and evidence confidence (is the data trustworthy) are separate axes — report both, never collapse into one number.
- Model/football/market/user-view disagreement is surfaced (`decision_fusion.py`), never hard-coded toward a specific player or outcome — the rule engine decides based on evidence tiers (persistent trend vs single-match signal), not on which player is involved.

## Dashboard development rules

**`DESIGN.md` is the authority for the React frontend (`frontend/`)** (rewritten 2026-09-09). Read it before any visual change. It carries the palette, the four type registers (including the one real job monospace has), the flat/no-shadow elevation model, the football language (pitch geometry, formation rule, fixture chips, opposed bars, shot map), the three-motion system, the chart contract (`lib/chartTheme.ts`), table and loading/error/empty rules, the seven screen identities, and a set of honesty rules that outrank aesthetics. Where that document and the code disagree, the code is the bug. The rules below remain in force and are the decision-layer half of the same contract.

- Organize around the decision workflow (what should I do → why → alternatives → what happens if I wait → what does my squad become → football evidence → confidence), never around one panel per dataset.
- No panel may show a recommendation that could contradict the Primary Decision panel. A different *question* (e.g. Optimizer Delta's from-scratch rebuild) is fine — but it must be visually secondary (collapsed/"Advanced") and explicitly labeled as answering something else.
- Visual hierarchy comes from scale/spacing/typography/position, not borders/glows/pills on every element.
- **Never guess a screenshot is fine from DOM text alone for a visual-design pass** — serve `data/dashboard.html` over a real localhost HTTP server (not `file://`, which renders as a static, non-interactive, non-compositing snapshot in this environment's browser tool) and take real screenshots at the required widths before declaring a visual pass done.
- Terminology is strict: ACTUAL vs LIVE vs NEXT-GW xP vs MULTI-GW PATH TOTAL vs DELTA VS ROLL — never call a full path total "Net EV", never call a stale number "live", never call an overlay "jointly optimized" if it isn't, never call an uncalibrated heuristic "calibrated".
- Cheap dashboard refresh vs expensive strategic recomputation are different operations. `fpl strategic-plan`'s beam search (~1 minute) plus its `--current-action` starting-action comparison (default on, real extra cost — one continuation search per meaningful starting action, roughly 2-10+ minutes depending on horizon/beam-width) run on `fpl strategic-plan` invocation only (manual, or wired into a real materiality trigger) — it is read from the decision journal on every dashboard regen, never re-run live. `analyze_transfer_decision`/`analyze_captain_decision` DO run live every regen (real, current data) but must never re-scan the same candidate pool more than once per regen — see `evaluate_locked_squad(ta=, ca=)`.
- **Desktop-first, permanently — not just a Phase 6 preference.** Design and verify at 1440px primary, 1080px secondary. Do not spend engineering effort on mobile-specific layout, and do not run mobile-viewport visual QA (`resize_window` preset "mobile" or width <768) unless the user explicitly asks — a real, repeated standing instruction (Phase 6 master brief: "again no more mobile shit"; repeated again 2026-09-03). A page merely "must remain usable" at narrow widths, never optimized for them.

## Data-source rules

- Tier 1 = official FPL API (no key). Tier 2-4 = journalism/lineups/odds connectors, real but lower-precedence and never trusted alone for a status change.
- A new external connector needs one real live-verification run (not just mocked tests) before being trusted — this project's own repeated lesson (Understat scraper break, live-odds bookmaker-index bug, FotMob name-matching) is that mocked payloads pass while the real integration silently no-ops.
- Team-name/player-name crosswalks go through `market_identity.py`'s shared normalizer — never a second, duplicated alias table per connector.
- **Independent-model benchmarks (Solio Analytics) are a comparison layer, never a projection input.** `solio-sync`/`external_benchmark.py` compare our own `expected_points()`/`decision_analysis` output against Solio's public projections and surface AGREEMENT/MINOR/MATERIAL/MAJOR_OUTLIER divergences with a component-level driver — a divergence is investigated, never auto-applied to correct our own model or auto-flip a decision (see the 2026-08-27 Bruno Fernandes finding below).

## Runtime / automation

Normal operation needs only: laptop on + the Windows Task Scheduler entries running (`FPLAgentSync` every ~15-360min, deadline/live-window-adaptive via `fpl run-scheduled`, `FPLAgentLivePoll` during a live matchday via `fpl live-match-poll`). No manual CLI invocation should be required for sync, dashboard regen, match analysis discovery, chip analysis, rank refresh, OR the multi-GW strategic plan itself — `fpl run-scheduled` chains: sync → odds/xg backfill → predicted-lineup/start-percent change detection → live-odds/player-odds sync → news sync → my-team sync → match discovery + analysis-queue enqueue → post-GW pipeline (materiality-gated) → **strategic-plan auto-trigger (materiality-gated, 2026-08-29)** → alert delivery → dashboard regen. The ONE thing that still needs a human-in-the-loop Claude Code session: the actual qualitative match-analysis reasoning step (`fpl match-analyze`, prompted automatically via `.claude/hooks/queue_check.py` on session start) — by design, this project's standing free-resources-only rule means no LLM API call happens from the unattended daemon itself.

**Optimizer auto-recompute (2026-08-29)**: `cli/main.py::_maybe_trigger_strategic_plan_recompute` fires a real `fpl strategic-plan` as a DETACHED background subprocess (never blocks `run_scheduled`, which Task Scheduler kills at a 10min `ExecutionTimeLimit`) whenever a real HIGH-severity `change_events` row has landed for a squad player since the last cached `strategic_plan` decision, the locked squad's own `squad_ids` no longer match what that decision was computed against (a real transfer/chip made outside the model), or no decision has ever been logged. Reuses `models/decision_freshness.py`'s own materiality bar - the same one the dashboard's RECOMPUTING banner already uses to disclose staleness - so that banner now self-heals within minutes instead of staying stuck until a human runs the CLI by hand. Overlap-guarded via `app_meta['strategic_plan_auto_started_at']` (self-healing after 15min, never a permanent lock).

Check `fpl scheduler-status` / `Get-ScheduledTask` to confirm both tasks are registered; `scripts/setup_scheduler.ps1` / `setup_live_poll_scheduler.ps1` (re-)register them. `FPLAgentLiveServer` (real-time SSE + dashboard serving) is the third real persistent task - `scripts/setup_live_server_scheduler.ps1` registers it.

**Reboot survival (2026-08-29, direct user requirement: "even if i shut down my laptop and the next day i turn it on, everything starts automatically")**: all 3 real scheduled tasks run with `LogonType=Interactive` (never a stored password/S4U - this project's own standing rule never handles credentials), so none of them can start before a human actually logs into Windows - a real, disclosed limit. A confirmed platform gap ruled out the cleaner fix (registering an `AtLogOn` scheduled-task trigger needs Administrator rights even for a task you already own - isolated live via a throwaway test task). The actual fix: `scripts/setup_startup_shortcut.ps1` places a real Windows Shortcut in the user's own Startup folder (`shell:startup`, no admin rights ever needed to write there) pointing at `scripts/startup_trigger_hidden.vbs` → `startup_trigger.ps1`, which fires `Start-ScheduledTask` for all 3 real tasks at every login - a safe no-op for any task already running (`-MultipleInstances IgnoreNew` + the real PID-based singleton lock, `scheduler/process_lock.py`). Verify with `Get-ScheduledTask` (all 3 should show `Running`/`Ready`, never `Disabled`) and confirm the shortcut exists at `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\fpl-agent startup.lnk`.

**Solio Analytics benchmark sync (2026-08-27)**: `ingestion/solio_source.py::sync_solio` is wired into `run_scheduled`, self-throttled to Solio's own stated ~4h cadence via an `app_meta['solio_last_synced_at']` gate (`config/freshness.yaml`'s `solio` key), so most scheduled ticks are a real no-op. Non-fatal on any fetch failure, same posture as every other opt-in source in this cycle.

## Commands (CLI, via `fpl`)

Run `fpl --help` for the full, current, real list (curated groups below — do not let this list drift from `fpl --help`, it is the ground truth):

- **Sync**: `sync`, `sync-history`, `sync-news`, `sync-live-odds`, `sync-player-odds`, `sync-eo`, `sync-predicted-lineups`, `sync-lineup-probability`, `sync-match`, `sync-crests`, `sync-elite-panel`, `solio-sync`, `backfill-odds`, `backfill-xg`, `backfill-cross-league`, `repair-understat-players`, `my-team`.
- **Decision**: `transfer-analysis`, `decision-fusion`, `model-benchmark`, `strategic-plan`, `decision-audit`, `season-sim`, `chips`, `captain`, `transfers`, `rate-team`, `build-team`, `build-squad`.
- **Intelligence**: `team-outlook`, `team-news`, `manager-changes`, `manager-intelligence`, `player-intelligence`, `match-report`, `match-analyze`, `match-note`, `analysis-queue`, `calibration-report`, `decision-backtest`, `decision-changes`, `points-changes`, `team-strength-backtest`.
- **Live**: `live-bonus`, `live-rank`, `live-watch`, `live-match-poll`, `post-gw-pipeline`.
- **Ops**: `run-scheduled`, `scheduler-status`, `doctor`, `readiness`, `status`, `source-status`, `storage`, `cleanup`, `backup`/`backups`/`verify-backup`/`restore`, `decisions`, `why`.
- **Dashboard**: `dashboard [--gw-window N] [--must-include ids] [--must-start ids] [--exclude ids]`.

## Tests

```
./.venv/Scripts/python.exe -m pytest tests/ -q
```

Full suite (1649 tests as of 2026-09-08, Phase 8.1) takes ~15-16 minutes. Run targeted files first when iterating (`pytest tests/test_decision_analysis.py tests/test_dashboard.py -q`), full suite before declaring anything done. `data/fpl.db` is the real production DB — tests never touch it (each test gets a fresh migrated in-memory-equivalent DB via the `db_conn` fixture); manual CLI runs against `data/fpl.db` are real and persist.

## Current known blockers (check before trusting related output)

These are **live** limitations - things that are still true and still
constrain what the system's output can be trusted to mean. Resolved
blockers and the full record of past fixes moved to
`docs/history/44-resolved-blockers-through-2026-09-09.md` on 2026-09-10;
consult it when you need the reasoning behind a past decision, not to
understand the system's current state.

- **Football-intelligence detectors are real but data-volume-gated, 2026-09-02**: `models/role_signal_detectors.py`'s ROLE_CHANGE/TACTICAL_CHANGE need >=2 real prior matches as a baseline (`_MIN_BASELINE_MATCHES`) — production currently has at most 2 real matches per player/team this early in the 2026-27 season, so both correctly produce zero signals right now (confirmed live, not a bug — will start firing as more real matches land). SET_PIECE_CHANGE fires today (real `player_setpiece_history` version changes) but is structurally capped at NEW_SIGNAL/MONITOR from this detector alone — a real order-change is anchored to exactly ONE real match, so it can only reach PERSISTENT_TREND with a second, independent real source (e.g. a later qualitative-skill reconfirmation) for a different match, an honest consequence of reusing `qualitative_trends.py`'s classifier unmodified rather than building a second one. `player_match_state.position`/`.touches_box` are confirmed 0/654 populated in production (FotMob's free feed doesn't carry them here) — ROLE_CHANGE uses a real shots/xG profile-shift proxy instead of literal position tracking, disclosed in the module's own docstring. Full account: `docs/history/41-session-2026-09-02-football-intelligence-phase3-finalization.md`.

- **Dixon-Coles team-strength ridge (`team_strength_dc.py::_RIDGE_LAMBDA=2.5`) is a disclosed, not-yet-backtest-tuned value** — added 2026-08-28 to fix a real confirmed bug (a newly-promoted team's single-match shock result running attack/defence to the optimizer's own bound, e.g. Hull's real GW1 2-0 win over Man Utd producing an 84% clean-sheet projection three GWs later). Verified live (Hull's CS range moved to a plausible 25-50%, real team differentiation preserved) and against a real historical backtest (identical MAE with/without the fix on 2025-26, since a completed season rarely has sparse-sample teams) - but the value itself hasn't been tuned against a real in-season small-sample case yet, since 2026-27 is still too early to backtest against. Re-tune once enough of the season has real results.

- **Team-strength `half_life_days=365.0` was tested against the direct hypothesis that it reacts too slowly to a real in-season form collapse (2026-09-12) and the hypothesis did NOT hold** — direct user complaint: a real wildcard build kept a strong goals-xP for Marmoush despite Spurs' real 0 goals across 3 finished 2026-27 matches. Built `backtesting/team_strength_backtest.py` (`fpl team-strength-backtest`) - a real walk-forward MAE of Dixon-Coles' own predicted per-team goals against real match_results_history goals, same no-leakage round-based discipline as `harness.py`. Ran it against half_life_days in {365 (live default), 240, 180, 150, 120, 90} across 4 real completed seasons (2022-23 through 2025-26): the live 365-day default had the LOWEST real goals MAE of every candidate, both overall and restricted to each season's first 3 rounds specifically (weighted overall MAE 0.9405 at 365 vs 0.9535 at 90; early-rounds MAE 0.8946 at 365 vs 0.9151 at 90) - shortening the half-life to "react faster" measurably WORSENED real historical accuracy, monotonically, at every step down. **`half_life_days`/`_RIDGE_LAMBDA` were NOT changed** on this evidence - team-goal accuracy was never actually broken. Following up on Marmoush's own specific numbers (production DB, same date): his real current-season sample is 2 matches (`matches_played=1.94`), real raw goals rate 0.0/90 but real xG rate 0.30/90 (0.59 total xG across 2 games, 0 conversions) - `shrunk_per90` for goals is 0.313 (already discounted well below a naive full-prior trust) while his `player_share_per90` of team goals (0.295, from `player_share_of_team_xg`/`_hierarchical_share_prior` - a genuinely separate mechanism from Dixon-Coles team strength) is roughly consistent with that real xG rate. Read together: this looks like normal finishing-variance-over-a-tiny-sample (a real, decent chance-creator who hasn't converted yet), not a stale team rating - the model is already doing the statistically defensible thing (not overreacting to 2 games), which is exactly what the backtest above independently confirms is the right call. The genuinely relevant lever for "should I trust this player to keep his role" turned out to be rotation/role risk (see the CONFIRMED_BENCHED fix directly below), not team-strength reaction speed.

- **A single real confirmed-lineup exclusion now discounts that one match's own projection immediately** (2026-09-12, direct user complaint: bought Foden in, Maresca benched him once, the model never reacted - "this type of intelligence, gamble... the human side of fpl" was completely absent). Root cause: `expected_minutes()`/`expected_points()` had no per-fixture concept of a real confirmed teamsheet at all, and the qualitative ROLE/MINUTES adjustment only fires on a real 2+-occurrence PERSISTENT_TREND - so one real, high-confidence, NON-predicted confirmed bench (`models/lineup_state.py` - an actual official teamsheet, never a FotMob "predicted" guess) moved nothing. Fixed via `models/expected_points.py::_confirmed_bench_probs` - discount-only (elementwise `min()` against the player's own empirical minutes-bucket distribution, so an already-pessimistic player is genuinely unaffected), bounded to a small non-zero substitute-cameo possibility rather than a hard zero, gated on a real official (non-"predicted") teamsheet for THAT specific fixture's own event, and skipped entirely (a pure perf guard, `_CONFIRMED_LINEUP_LOOKAHEAD_HOURS=48`) for any fixture more than 48h out, since a real teamsheet can't exist that early anyway. Wired into both `expected_points()` (single-match, feeds captaincy.py/squad.py) and `expected_points_window()` (multi-GW, the ONLY thing `optimization/transfers.py`'s whole beam search reads) - both the point estimate AND the Monte Carlo floor/ceiling/outcome-probability sampling read the same overridden distribution, so they never drift apart. Not backtest-calibrated (no historical CONFIRMED_BENCHED-vs-actual-minutes dataset exists yet) - a disclosed approximation, same honesty posture as `_NEW_SIGNING_MINUTES_DISCOUNT`. Real, disclosed scope limit not yet built: this is a single-event reaction, not a manager-identity/reputation memory - there is still no free source for "this specific manager tends to rotate after a signing arrives" as a standing prior (see the pre-existing "manager-change regime-shrink is not wired in" entry above, a related but separate gap).

- **Bonus/BPS is season-grain, not match-grain** — no source carries per-match BPS, so bonus regression is a season-level empirical-Bayes shrink, not the walk-forward match-level treatment the rest of `calibrated-v2` gets.

- **Predicted lineups: single real source** (fantasyfootballscout.co.uk) — every other free option checked is paywalled/403/a crowd-guessing game. A single-source gap, not a code bug.

- **Sampled effective ownership carries real margin of error** (~750-of-~10,000-manager sample) that is derived but not yet surfaced in any CLI/dashboard output.

- **Cross-league coverage for brand-new-to-PL signings is real but partial** — only La Liga/Bundesliga/Serie A/Ligue 1/Russia via Understat; a signing from an uncovered league (Eredivisie, Championship, etc.) gets the plain positional-average fallback, not a real personal signal.

- **Manager-change regime-shrink is not wired in** — `manager_change.py`'s real, 2-source-corroborated signal feeds display (team outlook) only; it does not yet trigger a faster prior-shrink in `expected_minutes`/`player_regression` the way other regime-change classes do. Deliberately deferred (real leakage-risk surface, not rushed).

- **Team-level qualitative signal does not reach Dixon-Coles** — by design (leakage-safety), not an oversight. A safe additive supplement (xG-regression on `team_match_state`) is a real, scoped, unbuilt follow-up.

- **Elite-manager historical panel has no data yet** — needs a real season to end and get snapshotted; first real payoff is next season.

- **Penalty-duty numeric adjustment is gated on sample size** — 2 real observed penalty shots league-wide so far, far short of the real 20-shot sufficiency bar `models/penalty_duty.py` itself sets before it would feed a conversion-rate adjustment.

- **Chip DP horizon is bounded to 5 GWs per window** (`optimization/chips.py::_WILDCARD_TRIAL_WINDOW_GW`) — fixed 2026-08-27 after a real bug let a long `--horizon` credit a wildcard with an unrealistic, permanently-uncontested advantage.

- **Live dependency recompute, audited 2026-08-28, not restructured**: the real chain (`change_events` -> materiality gate -> `_maybe_trigger_strategic_plan_recompute`) already satisfies the core "don't run the full optimizer for every source update" requirement (an unrelated non-squad player's change never triggers anything; a squad player's LOW-severity change is filtered out too) via a real two-tier split - `analyze_transfer_decision`/`analyze_captain_decision` (cheap) run live on every regen regardless, while only the expensive multi-GW beam search is gated behind a real HIGH-severity-change check. What does NOT exist: a fully staged, per-entity dependency graph (injury -> just that player's own xP cache invalidated -> just the squad decision re-checked -> strategy only if THAT changed) - once the gate fires, the trigger is a monolithic "re-run the whole `strategic-plan`", not a staged partial recompute. Real, legitimate, larger architecture project - not attempted this pass, honestly disclosed rather than restructured under time pressure.

- **Live snapshot channel extended, 2026-08-28**: `monitoring/live_snapshot.py` now also carries live bonus/DEFCON (per squad player, `models/live_bonus.py::compute_live_bonus` over the already-fetched live payload - no new network cost), recent squad-relevant `change_events` (last 24h, real lineup/injury/price signals), and decision freshness + the real "why did the recommendation change" explanation (`models/decision_change.py::latest_recommendation_change` - diffs the two most recent `strategic_plan` decisions' own CURRENT RECOMMENDED ACTION label, attributes a real change to its real triggering `change_events` row when one exists). `fpl decision-changes` CLI surfaces the same explanation (OLD/NEW/TRIGGER/TIME + one concise line) standalone. Real, disclosed scope limit: only explains a change to the cached `strategic_plan` recommendation specifically, not the always-live captain/transfer verdicts (which have no "previous decision" to diff against).

- **Correlation roadmap - assists/bonus audited and quantified, NOT rewritten, 2026-08-28**: real stress test against the actual locked squad's Man Utd trio (Bruno/Mbeumo/Maguire) found independent assist draws violate the real team-goals ceiling in 7.0% of trials (vs goals' own 34% before that fix) - a real but meaningfully smaller effect, matching the lower points-per-event and lower count-magnitude of assists vs goals. Bonus has no equivalent same-team hard-cap relationship to quantify the same way (FPL's real BPS pool spans all 22 on-pitch players, not just squad-tracked ones) - its real gap is intra-player (a player's OWN bonus should correlate with THEIR OWN trial's goals/assists, currently independent), not cross-player. Per the standing "only fix if materially affecting decisions" instruction: not rewritten this pass - the quantified 7% assist effect is real but not judged large enough on its own to justify building the missing "share of team assists" primitive (assists has no `player_share_of_team_xg`-equivalent to extend the goals fix from) under this session's time budget. Real, scoped, deferred follow-up.

- **Dashboard regen is ~1 minute** (down from ~4 minutes after the 2026-08-27 decision-object-consolidation fix — `evaluate_locked_squad` no longer re-scans candidates `analyze_transfer_decision`/`analyze_captain_decision` already computed). Remaining cost is distributed across Market/Fixture-Projections' per-fixture Dixon-Coles reads and Monte-Carlo robustness checks — a further, smaller, not-yet-attempted optimization.
