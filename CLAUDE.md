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
- **No subagent/Agent-tool dispatch for this project.** Standing user instruction: do implementation, investigation, and fixes directly with Read/Edit/Bash/Grep in the main thread, even for large multi-file work. This is a durable rule, not a one-off.
- **Autonomous authorization.** Proceed through a pillar/plan/audit's full cycle without stopping for confirmation at each step; report at natural completion points. Still applies the project's own review discipline (tests, live verification) as the substitute for a human checkpoint.

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
| Multi-GW strategic path search (1/3/5/8-GW), jointly chip-aware, single authoritative CURRENT RECOMMENDED ACTION | `optimization/strategic_planner.py` (`build_strategic_plan`, `synthesize_current_recommendation`), `optimization/transfers.py` (`search_transfer_sequences`, `compare_starting_actions`) |
| Real structurally-diverse top-N strategic paths (never the raw beam's own near-duplicate top-N) + real per-path 3/5/8GW breakdown | `optimization/transfers.py` (`build_diverse_paths`, `checkpoint_breakdown`) |
| Chip timing (single-decision-point functions + independent cross-check DP; joint in-beam chip choice lives in transfers.py above) | `optimization/chips.py` |
| Model vs football-evidence vs user-view fusion | `models/decision_fusion.py` |
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
| Dashboard | `monitoring/dashboard/` (package: `assemble.py` entry point, `home.py`/`plan.py`/`squad.py`/`intelligence.py`/`market.py`/`opportunity.py`/`fixtures.py` workspaces, `data_payload.py` embedded-JSON snapshot, `legacy.py` not-yet-migrated Advanced/Live/Team-Outlook/Match-Intelligence panels) |
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

## Data-source rules

- Tier 1 = official FPL API (no key). Tier 2-4 = journalism/lineups/odds connectors, real but lower-precedence and never trusted alone for a status change.
- A new external connector needs one real live-verification run (not just mocked tests) before being trusted — this project's own repeated lesson (Understat scraper break, live-odds bookmaker-index bug, FotMob name-matching) is that mocked payloads pass while the real integration silently no-ops.
- Team-name/player-name crosswalks go through `market_identity.py`'s shared normalizer — never a second, duplicated alias table per connector.
- **Independent-model benchmarks (Solio Analytics) are a comparison layer, never a projection input.** `solio-sync`/`external_benchmark.py` compare our own `expected_points()`/`decision_analysis` output against Solio's public projections and surface AGREEMENT/MINOR/MATERIAL/MAJOR_OUTLIER divergences with a component-level driver — a divergence is investigated, never auto-applied to correct our own model or auto-flip a decision (see the 2026-08-27 Bruno Fernandes finding below).

## Runtime / automation

Normal operation needs only: laptop on + the Windows Task Scheduler entries running (`FPLAgentSync` every ~15-360min, deadline/live-window-adaptive via `fpl run-scheduled`, `FPLAgentLivePoll` during a live matchday via `fpl live-match-poll`). No manual CLI invocation should be required for sync, dashboard regen, match analysis discovery, chip analysis, rank refresh, OR the multi-GW strategic plan itself — `fpl run-scheduled` chains: sync → odds/xg backfill → predicted-lineup/start-percent change detection → live-odds/player-odds sync → news sync → my-team sync → match discovery + analysis-queue enqueue → post-GW pipeline (materiality-gated) → **strategic-plan auto-trigger (materiality-gated, 2026-08-29)** → alert delivery → dashboard regen. The ONE thing that still needs a human-in-the-loop Claude Code session: the actual qualitative match-analysis reasoning step (`fpl match-analyze`, prompted automatically via `.claude/hooks/queue_check.py` on session start) — by design, this project's standing free-resources-only rule means no LLM API call happens from the unattended daemon itself.

**Optimizer auto-recompute (2026-08-29)**: `cli/main.py::_maybe_trigger_strategic_plan_recompute` fires a real `fpl strategic-plan` as a DETACHED background subprocess (never blocks `run_scheduled`, which Task Scheduler kills at a 10min `ExecutionTimeLimit`) whenever a real HIGH-severity `change_events` row has landed for a squad player since the last cached `strategic_plan` decision, the locked squad's own `squad_ids` no longer match what that decision was computed against (a real transfer/chip made outside the model), or no decision has ever been logged. Reuses `models/decision_freshness.py`'s own materiality bar - the same one the dashboard's RECOMPUTING banner already uses to disclose staleness - so that banner now self-heals within minutes instead of staying stuck until a human runs the CLI by hand. Overlap-guarded via `app_meta['strategic_plan_auto_started_at']` (self-healing after 15min, never a permanent lock).

Check `fpl scheduler-status` / `Get-ScheduledTask` to confirm both tasks are registered; `scripts/setup_scheduler.ps1` / `setup_live_poll_scheduler.ps1` (re-)register them.

**Solio Analytics benchmark sync (2026-08-27)**: `ingestion/solio_source.py::sync_solio` is wired into `run_scheduled`, self-throttled to Solio's own stated ~4h cadence via an `app_meta['solio_last_synced_at']` gate (`config/freshness.yaml`'s `solio` key), so most scheduled ticks are a real no-op. Non-fatal on any fetch failure, same posture as every other opt-in source in this cycle.

## Commands (CLI, via `fpl`)

Run `fpl --help` for the full, current, real list (curated groups below — do not let this list drift from `fpl --help`, it is the ground truth):

- **Sync**: `sync`, `sync-history`, `sync-news`, `sync-live-odds`, `sync-player-odds`, `sync-eo`, `sync-predicted-lineups`, `sync-lineup-probability`, `sync-match`, `sync-elite-panel`, `solio-sync`, `backfill-odds`, `backfill-xg`, `backfill-cross-league`, `repair-understat-players`, `my-team`.
- **Decision**: `transfer-analysis`, `decision-fusion`, `model-benchmark`, `strategic-plan`, `decision-audit`, `season-sim`, `chips`, `captain`, `transfers`, `rate-team`, `build-team`, `build-squad`.
- **Intelligence**: `team-outlook`, `team-news`, `manager-changes`, `manager-intelligence`, `player-intelligence`, `match-report`, `match-analyze`, `match-note`, `analysis-queue`, `calibration-report`, `decision-backtest`, `decision-changes`.
- **Live**: `live-bonus`, `live-rank`, `live-watch`, `live-match-poll`, `post-gw-pipeline`.
- **Ops**: `run-scheduled`, `scheduler-status`, `doctor`, `readiness`, `status`, `source-status`, `storage`, `cleanup`, `backup`/`backups`/`verify-backup`/`restore`, `decisions`, `why`.
- **Dashboard**: `dashboard [--gw-window N] [--must-include ids] [--must-start ids] [--exclude ids]`.

## Tests

```
./.venv/Scripts/python.exe -m pytest tests/ -q
```

Full suite (1122 tests as of 2026-08-28) takes ~10 minutes. Run targeted files first when iterating (`pytest tests/test_decision_analysis.py tests/test_dashboard.py -q`), full suite before declaring anything done. `data/fpl.db` is the real production DB — tests never touch it (each test gets a fresh migrated in-memory-equivalent DB via the `db_conn` fixture); manual CLI runs against `data/fpl.db` are real and persist.

## Current known blockers (check before trusting related output)

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
