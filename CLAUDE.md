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
| Chip timing (single-decision-point functions + independent cross-check DP; joint in-beam chip choice lives in transfers.py above) | `optimization/chips.py` |
| Model vs football-evidence vs user-view fusion | `models/decision_fusion.py` |
| Adversarial Decision Audit - tries to disprove the current winning recommendation (causal trace, per-player MODEL-vs-FOOTBALL, counterfactual stress tests + analytic falsifiers, multi-horizon alternative-action audit, league-wide/cold-start/qualitative checks, scorecard) | `optimization/adversarial_audit.py` (`run_adversarial_audit`) - expensive, manual (`fpl decision-audit`), cached in the decisions journal like `strategic_plan` |
| Projection confidence / evidence tiering | `models/projection_confidence.py`, `models/robustness.py`, `models/value_of_information.py` |
| Cold-start / new-transfer / regime handling | `models/expected_minutes.py`, `models/squad_churn.py`, `models/player_regression.py` |
| Match-level qualitative evidence (LLM + zero-LLM) | `models/match_intelligence.py`, `models/statistical_evidence.py`, `.claude/skills/match-intelligence-analysis/` |
| Team/player/manager intelligence rollups | `models/team_outlook.py`, `models/team_intelligence.py`, `models/player_intelligence.py`, `models/manager_intelligence.py` |
| GW lifecycle + autonomous post-GW pipeline | `models/gw_lifecycle.py`, `optimization/post_gw_pipeline.py` |
| Live rank (honest, degenerate-sample-aware) | `models/live_rank.py` |
| Dashboard | `monitoring/dashboard/` (package: `assemble.py` entry point, `home.py`/`plan.py`/`squad.py` workspaces, `data_payload.py` embedded-JSON snapshot, `legacy.py` not-yet-migrated panels) |
| Calibration / prediction-vs-outcome storage | `models/calibration.py`, `prediction_outcomes` table |

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

## Runtime / automation

Normal operation needs only: laptop on + the Windows Task Scheduler entries running (`FPLAgentSync` every ~30min via `fpl run-scheduled`, `FPLAgentLivePoll` during a live matchday via `fpl live-match-poll`). No manual CLI invocation should be required for sync, dashboard regen, match analysis discovery, chip analysis, or rank refresh — `fpl run-scheduled` chains: sync → odds/xg backfill → predicted-lineup/start-percent change detection → live-odds/player-odds sync → news sync → my-team sync → match discovery + analysis-queue enqueue → post-GW pipeline (materiality-gated) → alert delivery → dashboard regen. The ONE thing that still needs a human-in-the-loop Claude Code session: the actual qualitative match-analysis reasoning step (`fpl match-analyze`, prompted automatically via `.claude/hooks/queue_check.py` on session start) — by design, this project's standing free-resources-only rule means no LLM API call happens from the unattended daemon itself.

Check `fpl scheduler-status` / `Get-ScheduledTask` to confirm both tasks are registered; `scripts/setup_scheduler.ps1` / `setup_live_poll_scheduler.ps1` (re-)register them.

## Commands (CLI, via `fpl`)

Run `fpl --help` for the full, current, real list (curated groups below — do not let this list drift from `fpl --help`, it is the ground truth):

- **Sync**: `sync`, `sync-history`, `sync-news`, `sync-live-odds`, `sync-player-odds`, `sync-eo`, `sync-predicted-lineups`, `sync-lineup-probability`, `sync-match`, `sync-elite-panel`, `backfill-odds`, `backfill-xg`, `backfill-cross-league`, `my-team`.
- **Decision**: `transfer-analysis`, `decision-fusion`, `strategic-plan`, `decision-audit`, `season-sim`, `chips`, `captain`, `transfers`, `rate-team`, `build-team`, `build-squad`.
- **Intelligence**: `team-outlook`, `team-news`, `manager-changes`, `manager-intelligence`, `player-intelligence`, `match-report`, `match-analyze`, `match-note`, `analysis-queue`, `calibration-report`.
- **Live**: `live-bonus`, `live-rank`, `live-watch`, `live-match-poll`, `post-gw-pipeline`.
- **Ops**: `run-scheduled`, `scheduler-status`, `doctor`, `readiness`, `status`, `source-status`, `storage`, `cleanup`, `backup`/`backups`/`verify-backup`/`restore`, `decisions`, `why`.
- **Dashboard**: `dashboard [--gw-window N] [--must-include ids] [--must-start ids] [--exclude ids]`.

## Tests

```
./.venv/Scripts/python.exe -m pytest tests/ -q
```

Full suite (~950+ tests) takes 6-8 minutes. Run targeted files first when iterating (`pytest tests/test_decision_analysis.py tests/test_dashboard.py -q`), full suite before declaring anything done. `data/fpl.db` is the real production DB — tests never touch it (each test gets a fresh migrated in-memory-equivalent DB via the `db_conn` fixture); manual CLI runs against `data/fpl.db` are real and persist.

## Current known blockers (check before trusting related output)

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
