# FPL Agent

Persistent, resource-bounded FPL 2026/27 personal decision-support system. Full original spec: `../FPL 2026-27 — Claude Code Ultimate Autonomous FPL System — Optimized Master Bootstrap Prompt.md` (parent dir) — do not copy that spec's content back into this file.

**Documentation map** (2026-08-27 cleanup — this file used to be ~6300 lines of session-by-session narrative; that history is preserved, not deleted, in `docs/history/`):
- **This file** — operating manual: constraints, architecture, conventions, commands, current blockers.
- `docs/PROJECT_STATE.md` — current capabilities, known gaps, production state, next recommended work, verification procedure. Read this first when resuming work.
- `docs/history/` — full dated session narrative (every bug found, every design decision, every live-verification). Reference only when you need the *why* behind something specific; not required reading to work on the project.

## Mission

Take the user from preseason → GW1 → GW38 → season audit, answering one question well: **what should I do now, and why**. Recommend only; never auto-submit transfers/captain/chips.

## Non-negotiable constraints

- **No fabrication.** Never invent prices, injuries, transfers, fixtures, lineups, rules, stats, deadlines, confidence, or a "live" data point that isn't real. If unverifiable: say so. A degraded/absent signal is reported as absent, never approximated into something that reads as more certain than it is (see the live-rank precision handling below for the canonical example).
- **Recommend, never act.** No auto-submission of transfers/captain/chips anywhere in this system.
- **One authoritative recommendation.** Every dashboard panel must agree with `optimization.decision_analysis` (`analyze_transfer_decision`/`analyze_captain_decision`). No panel computes a second, independently-reasoned recommendation that could contradict it — panels that show a *different* question (e.g. "what if I rebuilt from scratch") must label it as such, not as an alternative recommendation.
- **Free resources only.** No paid APIs/services for new data connectors.
- **No subagent/Agent-tool dispatch for this project.** Standing user instruction: do implementation, investigation, and fixes directly with Read/Edit/Bash/Grep in the main thread, even for large multi-file work. This is a durable rule, not a one-off. **Also applies to any installed skill's own suggestion to delegate.** `critique` (installed 2026-09-03, see Skills section below) explicitly suggests spawning a sub-agent per assessment — its own text names a fallback ("If sub-agents are not available in the current environment, complete each assessment sequentially") — always take that fallback here, never the sub-agent path, regardless of what the skill's own instructions say.
- **Autonomous authorization.** Proceed through a pillar/plan/audit's full cycle without stopping for confirmation at each step; report at natural completion points. Still applies the project's own review discipline (tests, live verification) as the substitute for a human checkpoint.

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
| Real "why did the recommendation change" explanation + lightweight live-state channel | `models/decision_change.py`, `monitoring/live_snapshot.py`, `fpl decision-changes` |
| Historical Understat player-id re-resolution repair (real, no fabrication - re-fetches the real match page, never guesses) | `ingestion/understat_source.py::repair_unresolved_player_ids`, `fpl repair-understat-players` |
| Cached-decision staleness disclosure (age, `change_events`-backed materiality check) | `models/decision_freshness.py` (`assess_recommendation_freshness`) |
| Real per-GW starting XI/bench/captain/vice for a projected future squad state | `optimization/squad.py` (`resolve_projected_xi`, `build_player_pool_for_ids`) |
| Automatic, materiality-gated optimizer recompute (the daemon's own "the optimizer must run automatically" closer) | `cli/main.py::_maybe_trigger_strategic_plan_recompute`, wired into `run_scheduled` |
| Probabilistic minutes model (P(0)/P(1-59)/P(60+), empirical when ≥4 recent matches exist) | `models/minutes_distribution.py::minutes_bucket_probabilities` |
| Correlated Monte Carlo scenario sampling (same-fixture players share one drawn scoreline, not independent draws) | `models/scenario_engine.py::sample_season_scenarios` |
| Cold-start / new-transfer / regime handling | `models/expected_minutes.py`, `models/squad_churn.py`, `models/player_regression.py` |
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
- **Intelligence**: `team-outlook`, `team-news`, `manager-changes`, `manager-intelligence`, `player-intelligence`, `match-report`, `match-analyze`, `match-note`, `analysis-queue`, `calibration-report`, `decision-backtest`, `decision-changes`, `points-changes`.
- **Live**: `live-bonus`, `live-rank`, `live-watch`, `live-match-poll`, `post-gw-pipeline`.
- **Ops**: `run-scheduled`, `scheduler-status`, `doctor`, `readiness`, `status`, `source-status`, `storage`, `cleanup`, `backup`/`backups`/`verify-backup`/`restore`, `decisions`, `why`.
- **Dashboard**: `dashboard [--gw-window N] [--must-include ids] [--must-start ids] [--exclude ids]`.

## Tests

```
./.venv/Scripts/python.exe -m pytest tests/ -q
```

Full suite (1411 tests as of 2026-09-02) takes ~15 minutes. Run targeted files first when iterating (`pytest tests/test_decision_analysis.py tests/test_dashboard.py -q`), full suite before declaring anything done. `data/fpl.db` is the real production DB — tests never touch it (each test gets a fresh migrated in-memory-equivalent DB via the `db_conn` fixture); manual CLI runs against `data/fpl.db` are real and persist.

## Current known blockers (check before trusting related output)

- **FIXED 2026-09-02**: real, confirmed recurrence of "dashboard shows no squad" — a DIFFERENT root cause from the 2026-08-29 fix below. `cli/main.py::match_analyze_cmd` calls the real `_write_dashboard()` whenever a real `fpl match-analyze` run produces `change_events_written > 0`. `tests/test_cli_match_analyze.py` and `tests/test_cli_match_intelligence.py` both invoke that real command via `CliRunner` against an isolated `db_conn` fixture (Arsenal vs a synthetic "Coventry City"/COV) but never isolated `main_mod.DATA_DIR` the way `test_cli_live_match_poll.py`'s own `_isolated_live_poll_lock` fixture already does for the identical bug class there — so every full-suite run that reached these tests silently overwrote the REAL `data/dashboard.html` with the tests' own fixture content (confirmed live, byte-for-byte: "Real full-time headline"/"won at home" match the test payload verbatim). The read side was already correctly isolated (`db_conn` patches `database.connection.DATA_DIR`/`DB_PATH`), only the write destination wasn't. Fixed by adding the same `DATA_DIR`-isolation autouse fixture to both files. Real, separate, confirmed-and-fixed-in-the-same-session bug: Phase 5E's own edit briefly introduced a circular import in `strategic_planner.py` (top-level `authoritative_decision` import — fixed via `TYPE_CHECKING`/lazy import), which made the real scheduled `run-scheduled` task's own dashboard regen fail at 21:33:44 that day, so it couldn't self-heal the corrupted file until a manual regen.
- **Football-intelligence detectors are real but data-volume-gated, 2026-09-02**: `models/role_signal_detectors.py`'s ROLE_CHANGE/TACTICAL_CHANGE need >=2 real prior matches as a baseline (`_MIN_BASELINE_MATCHES`) — production currently has at most 2 real matches per player/team this early in the 2026-27 season, so both correctly produce zero signals right now (confirmed live, not a bug — will start firing as more real matches land). SET_PIECE_CHANGE fires today (real `player_setpiece_history` version changes) but is structurally capped at NEW_SIGNAL/MONITOR from this detector alone — a real order-change is anchored to exactly ONE real match, so it can only reach PERSISTENT_TREND with a second, independent real source (e.g. a later qualitative-skill reconfirmation) for a different match, an honest consequence of reusing `qualitative_trends.py`'s classifier unmodified rather than building a second one. `player_match_state.position`/`.touches_box` are confirmed 0/654 populated in production (FotMob's free feed doesn't carry them here) — ROLE_CHANGE uses a real shots/xG profile-shift proxy instead of literal position tracking, disclosed in the module's own docstring. Full account: `docs/history/41-session-2026-09-02-football-intelligence-phase3-finalization.md`.
- **FIXED 2026-08-29**: `has_material_change_since` (shared by the dashboard's RECOMPUTING/STALE freshness check AND `cli/main.py::_maybe_trigger_strategic_plan_recompute`) treated a `kickoff_reminder` change_events row as a real reason to consider the strategic plan stale, purely because that event type is deliberately hardcoded HIGH severity in `ingestion/change_detection.py::detect_upcoming_kickoffs` - but that label was calibrated for a different real consumer (the alerts panel: "your squad's match starts soon"), not for "does this invalidate the plan." A kickoff happening carries zero new player/price/lineup information - excluded `event_type='kickoff_reminder'` explicitly from the query rather than lowering its real, correct alert severity. Full account: `docs/history/36-session-2026-08-29-recomputing-severity-overload-bug.md`.

- **FIXED 2026-08-29**: full ApexCharts visualization-system rebuild (direct user escalation: charts "look like poop"/"hot dogshit" even after the earlier Chart.js->ApexCharts library swap). Every quantitative chart now uses the real ApexCharts type matched to its data semantics (datetime axis + real squad goal/card annotations for live rank/points, stepline for discrete FPL points, column/grouped-column for captain contribution and actual-vs-expected, diverging area for momentum replacing hand-rolled SVG) plus 4 genuinely new charts (projection floor/median/ceiling range, Dixon-Coles team-strength bar, xG-vs-xA scatter, per-match player-form line) built from real, already-computed data - zero fabrication. 6 real bugs found+fixed live via actual browser console/screenshots (not assumed): a `baseChart()` helper that flattened chart-level config instead of nesting under ApexCharts' required `chart:` key (broke every chart identically), a `market_teams`/`teams` id-space mismatch that mislabeled team-strength bars with raw numeric ids, a JS-function `fill.opacity` unsupported for ApexCharts bars (rendered solid black), a stale long-running `live-server` process serving pre-rewrite SVG momentum markup over its own SSE channel, axis-precision collapse on sub-1 xG/xA values, and new permanent per-chart error isolation so one bad payload can never blank every other real chart on the page again. New persistent `window.dashboardCharts` registry with real incremental `appendData` (no more destroy-recreate every ~10s poll). Full account: `docs/history/35-session-2026-08-29-apexcharts-visualization-rebuild.md`.

- **FIXED 2026-08-29**: real intermittent "dashboard randomly shows no squad" bug, direct user report. Root cause: `ingestion/my_team.py::get_latest_squad` ran TWO separate un-transacted `SELECT`s (`MAX(event)`, then picks `WHERE event=?`) - a real concurrent writer (this project's own scheduled `run-scheduled`/`_upsert_picks`, independent of any interactive session, running against the same real `data/fpl.db`) doing a real `DELETE`+re-`INSERT` for that event could land between them, so the second `SELECT` could see zero rows despite the first proving the event exists seconds earlier - a genuine torn read, never a raised exception, which is why no prior incident left any log trace. Fixed by making it one real atomic statement (a scalar subquery for the max event). Also added a diagnostic warning to the narrower residual race in `optimization/locked_squad.py::_xi_from_real_picks` (same event, already resolved, picks table momentarily empty) so a future recurrence is loggable, and raised the sqlite connection timeout (`database/connection.py`, 5s default -> 30s) as general defensive hardening against real cross-process contention on the same DB file. Because `data/dashboard.html` is a static file only regenerated periodically (scheduler or manual), one bad read baked a broken "no squad" state into it for up to ~30 minutes - refreshing the browser never helped since the file itself was the broken artifact, not a live-rendered page.

- **Dixon-Coles team-strength ridge (`team_strength_dc.py::_RIDGE_LAMBDA=2.5`) is a disclosed, not-yet-backtest-tuned value** — added 2026-08-28 to fix a real confirmed bug (a newly-promoted team's single-match shock result running attack/defence to the optimizer's own bound, e.g. Hull's real GW1 2-0 win over Man Utd producing an 84% clean-sheet projection three GWs later). Verified live (Hull's CS range moved to a plausible 25-50%, real team differentiation preserved) and against a real historical backtest (identical MAE with/without the fix on 2025-26, since a completed season rarely has sparse-sample teams) - but the value itself hasn't been tuned against a real in-season small-sample case yet, since 2026-27 is still too early to backtest against. Re-tune once enough of the season has real results.
- **Bonus/BPS is season-grain, not match-grain** — no source carries per-match BPS, so bonus regression is a season-level empirical-Bayes shrink, not the walk-forward match-level treatment the rest of `calibrated-v2` gets.
- **Predicted lineups: single real source** (fantasyfootballscout.co.uk) — every other free option checked is paywalled/403/a crowd-guessing game. A single-source gap, not a code bug.
- **Sampled effective ownership carries real margin of error** (~750-of-~10,000-manager sample) that is derived but not yet surfaced in any CLI/dashboard output.
- **Cross-league coverage for brand-new-to-PL signings is real but partial** — only La Liga/Bundesliga/Serie A/Ligue 1/Russia via Understat; a signing from an uncovered league (Eredivisie, Championship, etc.) gets the plain positional-average fallback, not a real personal signal.
- **Manager-change regime-shrink is not wired in** — `manager_change.py`'s real, 2-source-corroborated signal feeds display (team outlook) only; it does not yet trigger a faster prior-shrink in `expected_minutes`/`player_regression` the way other regime-change classes do. Deliberately deferred (real leakage-risk surface, not rushed).
- **Team-level qualitative signal does not reach Dixon-Coles** — by design (leakage-safety), not an oversight. A safe additive supplement (xG-regression on `team_match_state`) is a real, scoped, unbuilt follow-up.
- **Elite-manager historical panel has no data yet** — needs a real season to end and get snapshotted; first real payoff is next season.
- **Penalty-duty numeric adjustment is gated on sample size** — 2 real observed penalty shots league-wide so far, far short of the real 20-shot sufficiency bar `models/penalty_duty.py` itself sets before it would feed a conversion-rate adjustment.
- **Chip DP horizon is bounded to 5 GWs per window** (`optimization/chips.py::_WILDCARD_TRIAL_WINDOW_GW`) — fixed 2026-08-27 after a real bug let a long `--horizon` credit a wildcard with an unrealistic, permanently-uncontested advantage.
- **FIXED 2026-08-27**: `optimization/adversarial_audit.py::alternative_action_audit` now runs the same real `known_paths` cross-reference `strategic_planner.synthesize_current_recommendation` uses (`_known_paths_boost` — one extra `search_transfer_sequences` call at `beam_width=5`/the max horizon only, not per-horizon). Verified live against the real production DB: the audit's own ranking now matches a fresh `fpl strategic-plan` run's CURRENT RECOMMENDED ACTION exactly (both PLAY WILDCARD, path_total=642.12, `cross_check_against_strategic_plan` returns `None`). The earlier flagged disagreement (ROLL 611.55 vs 642.1) was confirmed to be entirely the missing cross-reference, not beam-width magnitude — closing it did not require forcing the two outputs to match. `cross_check_against_strategic_plan` stays permanently wired in as a safety net: a genuine disagreement can still surface if the cached `strategic_plan` decision has simply gone stale (real price/injury/lineup data moved since it was last logged) — that's real information, not a bug, and the fix doesn't (and shouldn't) suppress it. `fpl strategic-plan` and `fpl decision-audit` should be re-run reasonably close together in time when comparing their verdicts.
- **RESOLVED 2026-08-28** (was: "Real Solio-benchmark investigation, not yet resolved"): the B.Fernandes MAJOR_OUTLIER finding above traced to two REAL, CONFIRMED modeling bugs (not "insufficient evidence" as first thought) - fixed, not tuned to match Solio:
  1. **Shrinkage-prior cutover bug**: `_player_match_rates`' primary (current-season-Understat) branch shrank a player's goals/xa rate toward the bare CURRENT-SEASON position average the instant `matches_played > 0` (even one match), fully discarding a much larger, more informative prior-season record. Confirmed live: Haaland's real 2025-26 record (32.8 matches, shrunk goals90=0.73) collapsed to 0.22 after one real 2026-27 blank. Fixed: `models/expected_points.py::_hierarchical_prior_rates` computes a per-stat prior from the player's own last-season `player_season_history` (falling back to the existing cross-league prior, then the original bare position average only as a last resort) and passes it as `player_shrunk_rates`' new `prior_overrides` param (`models/player_regression.py`).
  2. **Unshrunk share-of-team-xG bug** (the actual dominant driver of Bruno's specific case): `player_share_per90` - the real goals-formula input in the primary branch, not `shrunk_goals90` - was accumulated from CURRENT-season Understat rows only, with zero shrinkage. Bruno's one real 2026-27 match (3 shots, 0.041 xG) was a genuinely quiet one (2.3% of Man Utd's match xG that day), fully determining his share unshrunk. Fixed: `_hierarchical_share_prior` blends toward the player's real last-season share when they were at the SAME club both seasons (a real transfer-safety guard - a cross-club share is meaningless), and falls back to a rate-derived approximation (`shrunk_goals90 / league_average`, the same formula the zero-current-data branch already used) when they changed clubs - found live while tracing a second real case (Isak).
  - Real production result: Bruno's MAJOR_OUTLIER (+95% vs Solio) narrowed to MATERIAL_DIVERGENCE (+30%); many previously-outlier players (Cunha, Semenyo, Gabriel, Rogers, Virgil, Anderson, Thiago, Cherki) now show AGREEMENT. Team-level CS/xG was already in tight agreement before this fix (real cross-model sanity check, unaffected).
  - **Real, disclosed, still-open finding, NOT fixed this pass**: 56.5% of ALL historical `player_match_stats_history` rows (31,983/56,581, spanning 2021-22 through 2025-26) have `player_id IS NULL` - a real, large `resolve_player_id` backlog from BEFORE its 2026-08-26 team-scoped-fallback fix (diacritics/"B.Fernandes"-style abbreviated names) that was never retroactively re-run against already-inserted rows. No `player_name` text is persisted on this table (only `understat_player_id`, Understat's own id - confirmed stable, never mixed resolved/unresolved for the same id), so a repair needs a real re-scrape of historical Understat match pages, not a cheap in-DB backfill. This is the reason Bruno specifically stays at MATERIAL (not AGREEMENT) - his OWN 2025-26 rows are among the unresolved 56.5%, so fix #1 above found him a real prior-season RATE (via `player_season_history`, unaffected) but fix #2 (share) had no same-club last-season data to blend from. Real, scoped follow-up: a rate-limited historical re-scrape+re-resolve pass, its own dedicated session.
  - **Search-width experiment (2026-08-28)**: real production run, beam_width 5 vs 10 vs 20 vs 50 (5-GW horizon, no-current-action/no-chips for isolation) - the #1 path (PLAY WILDCARD -> 3XC -> BBOOST, path_total=329.38) was IDENTICAL at every width; wider beams only surfaced near-duplicate tail variants (<1.2pt from the leader). Beam width 5 is genuinely stable for this squad/horizon - kept, no search-method change made (per the standing "do not speculate, only replace if materially unstable" instruction). Runtime scaled roughly linearly: 61s/71s/115s/167s for 5/10/20/50.
  - **CORRECTED 2026-08-28 - the backtest MAE finding above was mis-explained**: full-season walk-forward MAE stayed byte-identical (1.1776) at first not because the fix's effect was "diluted by full-season averaging" (the original, incorrect explanation) but because `backtesting/harness.py::run_backtest` never called the fixed code path AT ALL - see the dedicated entry below for the real account (a genuine doc-drift bug: `core_expected_points()`'s docstring falsely claimed to be the harness's real entry point).
- **Real backtest-wiring gap found + fixed, real data-driven threshold added, 2026-08-28**: the hierarchical-prior fix above showed a byte-identical backtest MAE because `run_backtest` has always had its own separate, duplicated inline rate computation (`player_shrunk_rates` called directly, never through `_player_match_rates`/`core_expected_points` - that function's own docstring's claim to be "the entry point the walk-forward backtest harness scores against" was stale/false, corrected). Wired the fix in properly, then a real, valuable finding followed: applied unconditionally, it was net-HARMFUL (~1% MAE regression, consistent across every round the harness could measure, 1.1776 -> 1.1889) once a player already has 4+ real current-season matches - shrinking toward a possibly-stale prior-season rate once the current sample is already substantial adds bias, it doesn't reduce noise. Gated both the goals/xa rate prior and the share-of-team-xG prior to only apply below `_MIN_MATCHES_FOR_HIERARCHICAL_PRIOR=4` real current-season matches (matches `minutes_distribution.py::_MIN_MATCHES_FOR_EMPIRICAL`'s own established "enough real evidence" bar). Re-run after gating: MAE 1.1804 - a small, honest, disclosed residual versus the original 1.1776 baseline (the harness's own minutes-empirical gate already excludes the thinnest 0-3-match rows from scoring at all, so this residual sits at the threshold boundary), a real improvement over the ungated 1.1889. The live production case (Haaland/Bruno, real matches_played=1) sits well below the threshold and is unaffected by this gating - the fix's actual target window is exactly where this harness structurally can't measure at all, and the gating only prevents it from ALSO firing where real evidence shows it shouldn't.
- **Live-match-poll dashboard-regen perf bug, FOUND + FIXED 2026-08-28** (direct user P0: "do not rebuild the entire static dashboard every 15-30 seconds"): `live_match_poll_cmd` (the ~25s fast loop) called `_write_dashboard()` - the same real ~1-minute `generate_dashboard_html()` pipeline `fpl dashboard` uses - on every tick a match was live, real and confirmed to starve the loop's own configured interval back down to however long the full rebuild actually took. Fixed: the full dashboard now only regenerates on a real FULL_TIME transition; a new, genuinely cheap `monitoring/live_snapshot.py` (pure DB reads plus the already-fetched live payload - no Dixon-Coles/Monte-Carlo/beam-search) writes `data/live_snapshot.json` every tick instead, and new dashboard JS polls it every 20s to patch the live-rank/live-points tiles (`#live-rank-value`, `#live-points-value`) in place - live-verified in a real browser session (DOM value changed from a synthetic snapshot with zero page navigation). The old `<meta http-equiv="refresh">` full-page reload during LIVE state slowed 20s->90s accordingly (now a slower catch-all for everything else, not the primary live-update path).
- **Real scenario-engine correlation bug, FOUND + FIXED 2026-08-28** (direct user correlation audit): `sample_player_trial_points` drew each squad-tracked player's own goal count independently via `Binomial(team_goals, share)` per trial - correct for exactly one modeled scorer per team+fixture, but when two+ squad-tracked teammates share a fixture (a real, common case - this project's own locked squad has Bruno+Mbeumo both at Man Utd), independent draws could double-count the same real goal with nothing constraining the group's combined total to the real team total. Stress-tested against the OLD code: 34% of trials (1709/5000) violated the real team-goals constraint. Fixed: `scenario_sampling.py::sample_team_group_trial_points` jointly multinomial-attributes `team_goals` across same-team squad members (+ a residual "someone else" bucket); reduces to the exact existing binomial when there's only one tracked scorer (zero behavior change for that common case, verified). Live-verified against the real production squad (Bruno+Mbeumo+Maguire all Man Utd) - no crash, correct joint attribution. Assists/bonus stay independent per player - a real, disclosed, NOT-fixed gap (no team-relative "share of assists/bonus" primitive exists the way it does for goals); clean-sheet/opponent correlation was already correct (shares the same per-fixture drawn scoreline, unchanged).
- **Live dependency recompute, audited 2026-08-28, not restructured**: the real chain (`change_events` -> materiality gate -> `_maybe_trigger_strategic_plan_recompute`) already satisfies the core "don't run the full optimizer for every source update" requirement (an unrelated non-squad player's change never triggers anything; a squad player's LOW-severity change is filtered out too) via a real two-tier split - `analyze_transfer_decision`/`analyze_captain_decision` (cheap) run live on every regen regardless, while only the expensive multi-GW beam search is gated behind a real HIGH-severity-change check. What does NOT exist: a fully staged, per-entity dependency graph (injury -> just that player's own xP cache invalidated -> just the squad decision re-checked -> strategy only if THAT changed) - once the gate fires, the trigger is a monolithic "re-run the whole `strategic-plan`", not a staged partial recompute. Real, legitimate, larger architecture project - not attempted this pass, honestly disclosed rather than restructured under time pressure.
- **Decision-outcome backtest, BUILT 2026-08-28** (was: "not built this pass") - real deadline-freeze capture -> real GW-outcome reveal, same two-moment pattern `calibration.py` already established for player-level predictions. `models/decision_calibration.py` (`record_decision_snapshot`/`reveal_decision_outcomes`/`decision_backtest_summary`), migration 0034 (`decision_outcomes` table), wired into `run_scheduled`'s existing LOCKED-lifecycle capture point and the post-GW pipeline's existing reveal point - `fpl decision-backtest` reports it. Unifies ROLL-vs-best-available-transfer and recommended-vs-best-rejected-transfer into one stored comparison shape (`chosen_*`/`alt_*`, `alt` is always the single best-ranked candidate whether or not it was chosen); captain compares the recommended pick against the next-best real alternative the same way. Real first sample captured live against production (GW2, pre-deadline - Tzolis->player481 transfer recommendation, Haaland KEEP captain decision) - reveal happens automatically once GW2 finishes, no real completed-and-revealed sample exists yet (honestly disclosed by the CLI/report, never a fabricated n).
- **Historical Understat repair, STARTED 2026-08-28 for the 2025-26 season** (was: "31,983/56,581 unresolved, needs a real re-scrape session") - `ingestion/understat_source.py::repair_unresolved_player_ids` re-fetches each real unresolved match's own Understat page (the `understat_match_id` already stored per row) and re-runs the same team-scoped `resolve_player_id` fallback every other real Understat caller trusts - never guesses/fabricates a name mapping, zero duplicate-row risk (UPDATE by row id only, never INSERT). Real production run against the highest-value season (2025-26, directly feeds the live hierarchical-prior fix): 379/380 matches processed, 1605/4222 rows resolved (38%, up from the old ~7% rate measured on the oldest 2021-22 batch - most of the remainder is genuinely players no longer in this project's live `players` table, an honest non-fabricatable gap, not a repair-logic miss). **Confirmed real, measured downstream effect**: Bruno Fernandes' own 2025-26 same-club data is now fully resolved - his real share-of-team-xG prior went from the rate-derived fallback (no real last-season share data) to his own genuine historical share, and he dropped out of the top Solio-divergence list entirely (was MATERIAL_DIVERGENCE). Older seasons (2021-22 through 2024-25, ~27,700 rows) not yet repaired - real, scoped follow-up, `fpl repair-understat-players --season <season>` is the reusable command, `--season` strongly recommended (unscoped defaults to oldest-first, the lowest-value order).
- **Live snapshot channel extended, 2026-08-28**: `monitoring/live_snapshot.py` now also carries live bonus/DEFCON (per squad player, `models/live_bonus.py::compute_live_bonus` over the already-fetched live payload - no new network cost), recent squad-relevant `change_events` (last 24h, real lineup/injury/price signals), and decision freshness + the real "why did the recommendation change" explanation (`models/decision_change.py::latest_recommendation_change` - diffs the two most recent `strategic_plan` decisions' own CURRENT RECOMMENDED ACTION label, attributes a real change to its real triggering `change_events` row when one exists). `fpl decision-changes` CLI surfaces the same explanation (OLD/NEW/TRIGGER/TIME + one concise line) standalone. Real, disclosed scope limit: only explains a change to the cached `strategic_plan` recommendation specifically, not the always-live captain/transfer verdicts (which have no "previous decision" to diff against).
- **Correlation roadmap - assists/bonus audited and quantified, NOT rewritten, 2026-08-28**: real stress test against the actual locked squad's Man Utd trio (Bruno/Mbeumo/Maguire) found independent assist draws violate the real team-goals ceiling in 7.0% of trials (vs goals' own 34% before that fix) - a real but meaningfully smaller effect, matching the lower points-per-event and lower count-magnitude of assists vs goals. Bonus has no equivalent same-team hard-cap relationship to quantify the same way (FPL's real BPS pool spans all 22 on-pitch players, not just squad-tracked ones) - its real gap is intra-player (a player's OWN bonus should correlate with THEIR OWN trial's goals/assists, currently independent), not cross-player. Per the standing "only fix if materially affecting decisions" instruction: not rewritten this pass - the quantified 7% assist effect is real but not judged large enough on its own to justify building the missing "share of team assists" primitive (assists has no `player_share_of_team_xg`-equivalent to extend the goals fix from) under this session's time budget. Real, scoped, deferred follow-up.
- **Dashboard regen is ~1 minute** (down from ~4 minutes after the 2026-08-27 decision-object-consolidation fix — `evaluate_locked_squad` no longer re-scans candidates `analyze_transfer_decision`/`analyze_captain_decision` already computed). Remaining cost is distributed across Market/Fixture-Projections' per-fixture Dixon-Coles reads and Monte-Carlo robustness checks — a further, smaller, not-yet-attempted optimization.
- **FIXED (fpl.page-parity performance pass)**: `optimization/locked_squad.py::_xi_from_real_picks` — the ONLY real caller of `get_locked_squad()`'s synced-squad branch — called `build_player_pool(conn, n_gw=1)` (a full ~600-player real Dixon-Coles/Monte-Carlo xP scan, measured ~6.2s against production) just to look up the 15 real picked player ids. `get_locked_squad()` sits on the hot path of `monitoring/live_snapshot.py`'s own ~20-25s live-match tick, which that module's own docstring already documents as required to stay cheap ("never runs Dixon-Coles, Monte Carlo... those stay on their own expensive, materiality-gated cadence") — this silently violated that contract every tick. Fixed to `build_player_pool_for_ids` (already existed, already used by `resolve_projected_xi`) — same real per-player xP, scoped to the 15 known ids. Measured 237ms against the same production data post-fix (~26x faster); `build_live_snapshot()` end-to-end went from ~6.6s to ~223ms.

## Agent execution style

DO NOT narrate routine tool usage.

During implementation:
- Do not say what command you are about to run.
- Do not summarize every file edit.
- Do not provide progress updates after individual commands.
- Do not report "ran X commands", "edited Y files", "+A -B", etc.
- Do not explain routine grep/read/edit/test operations.
- Work continuously until the requested task or a meaningful blocker is reached.

Only send a user-facing message when:
1. You need clarification or permission.
2. You hit a genuine blocker.
3. A major architectural decision needs approval.
4. The entire requested task is complete.

At completion, provide ONE concise report containing:
- what changed
- important bugs found
- tests run/result
- remaining issues
- any action required from the user

Do not emit periodic progress narration.

For long tasks, maintain project state in files rather than conversation text.
Prefer reading the relevant source files and existing project documentation over repeatedly re-explaining project context.

## FPL dashboard workflow

Do not spend conversational context explaining implementation progress.

For large dashboard work:
1. Inspect current implementation.
2. Form a private implementation plan.
3. Execute the plan continuously.
4. Run tests.
5. Regenerate production HTML.
6. Visually inspect the result — a real screenshot via a localhost server, not DOM text extraction (see Dashboard development rules above).
7. Fix regressions.
8. Only then report results.

Do not stop after each subtask to tell the user what you just did.
