# Session 21 — 2026-08-29: master automation pass, real architecture audit

Direct continuation, per an explicit "master product/optimizer/automation pass" spec covering ~40
P0/P1 items (event-driven freshness, dependency-based recomputation, automatic optimizer runs,
live-rank cadence, a full mathematical-architecture audit, backtesting/calibration, and more). Per
the spec's own explicit instruction ("DO NOT rebuild functioning subsystems blindly - first inspect
them"), this session led with real source inspection before writing any code, and found the existing
system already implements the large majority of the requested architecture. Real, scoped gaps were
fixed; the rest is reported honestly as already-covered, audited-and-sufficient, or genuinely
unbuilt future work (see the item-by-item mapping this session's own final report gives).

## Real gap #1: the optimizer never ran automatically (fixed)

Confirmed via direct inspection of `run_scheduled()`: real change detection already exists and
already produces real `change_events` rows every cycle (predicted-lineup changes, start-percent
changes, price changes, kickoff reminders) - but nothing in the chain ever re-ran the real ~2-10min
multi-GW beam search (`build_strategic_plan`/`synthesize_current_recommendation`). The dashboard's
own RECOMPUTING banner (built session 18, same day) could correctly DISCLOSE that a decision had
gone stale, but nothing ever ACTED on that disclosure - a human still had to run `fpl
strategic-plan` by hand.

Fixed: `cli/main.py::_maybe_trigger_strategic_plan_recompute`, wired into `run_scheduled`. Reuses
the exact materiality bar `models/decision_freshness.py` already established (HIGH-severity
`change_events` on a squad player since the last decision), plus a new check for the locked squad's
own `squad_ids` diverging from what the last decision was computed against (a transfer/chip made
directly in the official FPL app, which produces no player-level `change_events` row at all -
`strategic_plan`'s own logged detail now carries `squad_ids` to make this comparison possible).
Fires the real CLI command as a DETACHED background subprocess, never blocking `run_scheduled`
itself - a real, load-bearing constraint: Task Scheduler's own `FPLAgentSync` registration caps
`run_scheduled` at a 10-minute `ExecutionTimeLimit`, so blocking on the real search here could get
the whole sync cycle killed mid-run. Overlap-guarded via `app_meta`, self-healing after 15 minutes
if a prior run crashed rather than a permanent lock. 9 new tests
(`tests/test_strategic_plan_auto_trigger.py`), live-verified against the real production DB: the
underlying detection query correctly found 0 pending triggers right now (nothing material has
changed since the last real plan) and correctly identified 4 real historical HIGH-severity
`change_events` for squad players when queried directly, proving the signal is real, not silently
broken. A real `fpl run-scheduled` was run against production afterward and completed cleanly with
the new step wired in.

## Real gap #2: live-rank cadence was ~15min, not ~5min during a live GW (fixed)

`_maybe_refresh_livefpl_rank` only ever ran inside the slow `run_scheduled` cadence (best case
15min during a live window, the `freshness.yaml`-sourced adaptive interval). `fpl live-match-poll`
- a separate, already-registered (`FPLAgentLivePoll`), fast (~25s) polling loop for raw match
events - never touched live-rank at all. Fixed: `live_match_poll_cmd`'s loop now also calls
`_maybe_refresh_livefpl_rank` on every `any_live` tick; lowered `_LIVEFPL_MIN_REFRESH_MINUTES`
10->5 to match. Net effect: real live rank now refreshes on a genuine ~5min cadence during an
active gameweek, via the already-running fast loop, not the slow one.

## Real gap #3: `fpl scheduler-status` only ever checked one of the two real daemon tasks (fixed)

Confirmed live on the real dev machine: both `FPLAgentSync` and `FPLAgentLivePoll` are genuinely
registered and `Ready` - but the status command only ever queried `FPLAgentSync` by name, silently
saying nothing about the second real task either way. Fixed to report both. 1 new CLI-level test.

## Real invariant closed: CURRENT_FPL_STATE end-to-end proof

Session 18 built the underlying staleness-disclosure mechanism (`models/decision_freshness.py`,
home hero's RECOMPUTING banner) with real unit-level coverage - this session adds the missing
END-TO-END proof: `generate_dashboard_html()` itself, given a real locked squad, a real
`strategic_plan` decision, and a real HIGH-severity `change_events` row that postdates it, actually
renders RECOMPUTING - and, in the negative case, does NOT render it when nothing material changed.
2 new tests (`tests/test_dashboard.py`).

## Real architecture audit: most of the spec's math/optimizer asks are already built

Per the spec's own "inspect first" instruction, checked before assuming a gap existed:

- **Minutes model**: already a real P(0)/P(1-59)/P(60+) empirical distribution
  (`models/minutes_distribution.py::minutes_bucket_probabilities`, ≥4 recent matches -> empirical,
  else an honest fallback prior) - not a single point estimate. Already feeds
  `expected_appearance_points`/`_match_components`.
- **Correlated player/team outcomes**: `models/scenario_engine.py::sample_season_scenarios` already
  shares ONE drawn Dixon-Coles-correlated scoreline per real fixture across every player in it
  (`fixture_cache` keyed by fixture id) - same-team attackers are NOT independently sampled.
- **New-transfer/regime handling**: re-confirmed (session 18's Tzolis audit still holds) - the
  `understat` -> `season_fallback` -> `cross_league` -> `current_season_live_snapshot` cascade in
  `_player_match_rates` already exists and correctly prioritizes a player's own real current-season
  evidence over a stale historical prior the moment it exists.
- **Adaptive, deadline/live-window-aware scheduler cadence**: `scheduler/cadence.py::recommended_cadence`
  + `scheduler/adaptive.py::maybe_retighten_scheduler` already compute the real ideal poll interval
  from `config/freshness.yaml` and ACTUALLY RE-REGISTER the Windows Task Scheduler task with it,
  automatically, every cycle - a materially more complete system than assumed before reading it.
- **Restart recovery**: `setup_scheduler.ps1`'s `-StartWhenAvailable` already makes a missed
  trigger (laptop off overnight) catch up on next boot: combined with every sync step's own
  from-scratch reconciliation (diff current state vs last-known, not depend on continuous polling),
  this already substantially satisfies the "shutdown/restart/overnight gap" requirement without new
  code.
- **Calibration infrastructure**: `record_predictions_for_locked_squad`/
  `record_outcomes_for_finished_event` already run automatically inside `run_scheduled`/
  `post_gw_pipeline` - genuinely capturing real prediction-vs-outcome rows (confirmed live: 15 real
  rows exist). Real, honest limitation, not a bug: 15 rows (one gameweek's worth) is far too small
  for real calibration curves - this needs TIME (more finished gameweeks), not more engineering.

## Genuinely NOT attempted this session (real, scoped, comparable to a full prior pillar each)

Full component-based xP re-audit against a fresh literature/Copilot-methodology comparison beyond
what session 18's captain audit already covered; Dixon-Coles hierarchical/shrinkage retuning beyond
the existing disclosed `_RIDGE_LAMBDA` (needs more in-season data to retune responsibly, not
blocked on engineering); a formal walk-forward backtesting harness EXTENSION for calibration curves
specifically (the harness itself exists - `fpl backtest` - calibration curves need more finished
gameweeks of real data, not new code); a true SSE/WebSocket live-updating dashboard (the current
architecture is a static HTML file with no persistent server process - true push updates would need
a real always-on local web server, a genuine architecture change, not attempted given the project's
zero-new-heavy-infra posture); a synthetic isolated-scratch-runtime OS-process daemon integration
test harness (the REAL daemon was smoke-tested directly against production instead - a real `fpl
run-scheduled` run, live-verified clean, with the new auto-trigger step correctly evaluating and
declining to fire); full fpl.page product-surface parity (Points Changes rich UI, Template Team,
Elite Manager historical context - blocked on a season ending for the last one, others are real
scoped future UI work per session 19's own P1 audit).

## Tests

Full suite green (exact count in this session's own final report - grew by ~12 tests this session:
9 for the auto-trigger, 2 for the CURRENT_FPL_STATE invariant, 1 for scheduler-status). Live-verified:
a real `fpl run-scheduled` against the production DB completed cleanly with the new automation
wired in; a real dashboard regen confirmed clean (no stale-squad/RECOMPUTING artifacts); `fpl
scheduler-status` confirmed both real Task Scheduler entries are genuinely registered and `Ready`.
