<!-- Moved from CLAUDE.md during the 2026-08-27 documentation cleanup pass. Full session narrative, kept verbatim for reference - not required reading for day-to-day work. See docs/PROJECT_STATE.md for current state. -->

## GW1 postmortem: runtime root cause, cold-start fix, transfer fusion, calibration storage (2026-08-26)

New session, 5 real days after GW1 finished, opened with a broad audit request. Investigated first
rather than assuming anything was broken - most of the 20-section ask was already built in prior
sessions (see above); real work was diagnosing why the automation had actually gone stale and closing
the genuinely open gaps.

- **Root cause of "SessionStart doesn't process the qualitative queue"**: this session's own cwd was
  the parent `FPL/` folder, not `fpl-agent/` - the exact footgun this file already flagged once
  (Phase 6 section, "project-root caveat"). `fpl-agent/.claude/settings.json`'s SessionStart hook
  never loads from that root. **Fixed by mirroring the hook at the parent**: `FPL/.claude/settings.json`
  + `FPL/.claude/hooks/queue_check.py`, same non-fatal `fpl analysis-queue --pending` check, resolving
  `fpl-agent/` explicitly rather than relying on cwd. Now fires regardless of which of the two real
  starting directories a session uses.
- **Drained the real backlog this surfaced**: 14 of 15 queued GW1 jobs (all matches but Arsenal-
  Coventry, done in an earlier session) had sat unprocessed for days. Wrote real, evidence-grounded
  OBSERVED/INFERRED/FPL_IMPLICATION analysis for all remaining GW1 fixtures via `fpl match-analyze`
  (stale HALFTIME jobs auto-superseded once FULL_TIME exists - new `supersede_stale_halftime_jobs()`,
  wired into `fpl analysis-queue`, `run_scheduled`, and `live-match-poll`'s FULL_TIME transition, so
  this self-heals going forward, not just this once).
- **Real, high-severity bug found while draining the queue: Haaland's own GW1 match was invisible to
  the whole pipeline.** `match_intelligence` had a real row for Man City v Bournemouth
  (fotmob 5795370) stuck at `status='PRE_MATCH'` with `away_team_id=NULL`, days after the match
  finished - `market_identity.py::COMMON_TEAM_NAME_ALIASES` had no entry for FotMob's real payload
  name "AFC Bournemouth" (FPL's own short form is "Bournemouth"), so `_resolve_fpl_team_id` silently
  failed and the match was never auto-registered as analyzable, never enqueued for analysis. Added the
  alias, re-synced for real (22/22 players resolved, real result Man City 2-1 Bournemouth, Haaland
  5 shots/0.743xG/0 goals - genuine strong involvement, no actual return), analyzed it properly.
- **Real cold-start bug fixed, the actual Tzolis complaint**: `expected_minutes()` blended his real
  GW1 evidence (started, 75 real minutes) against his only prior-season row (326min, 2021/22, a
  multi-season-gap cameo, correctly flagged `stale_prior_season`) at just 10% current-weight - the
  `weight_current = min(finished_events/10, 0.8)` formula never accounted for the PRIOR's own
  reliability, only the current sample's size, so a stale prior kept dominating even once real
  current-season evidence existed. Produced an absurd 15.2 expected minutes for a player who just
  started and played 75. **Fixed with a separate, faster-ramping blend specifically for the
  current-evidence-vs-stale-prior case** (`weight_current = min(0.5 + 0.2*finished_events, 0.9)`) -
  Tzolis: 15.2 -> 54.0 expected minutes, xP 0.58 -> 2.23. The identical gap existed one level deeper:
  `_player_match_rates()` never read `player_stats_snapshot`'s own real, official, already-synced
  current-season goals/xG/assists/xA (season-cumulative fields FPL's API already reports) for a
  player with zero Understat match rows - his own real GW1 assist/xG never fed his own rate at all,
  only a stale prior-season/cross-league guess did. Added `models/player_regression.py::
  live_season_shrunk_rate()` (same `shrink_rate()` empirical-Bayes machinery, live-only by
  construction - gated on `as_of_date is None`, structurally unreachable from the walk-forward
  backtest) as a new fallback tier, preferred over both the stale season-history fallback and the
  cross-league guess whenever real current-season minutes exist. **This is a general fix, not a
  Tzolis patch** - both changes fire for any player whose only prior signal is stale/absent once real
  current-season evidence exists, matching the "actual GW performance must feed future projections"
  requirement directly.
- **Transfer Decision Fusion built** (`models/decision_fusion.py::compare_transfer_views`) - captain
  already had this (2026-08-22), transfers didn't (a real, previously-disclosed gap: "Transfer Watch
  recommended Tzolis -> Anderson... without any fusion"). Same rule-based verdict set (MODEL_WINS /
  QUALITATIVE_WINS / UNDECIDED / INSUFFICIENT_EVIDENCE), scoped to the model's own proposed
  transfer-OUT player specifically. A real, non-persistent one-match qualitative signal never forces
  an override (still `MODEL_WINS`, but the explanation names the real signal and frames it as
  HOLD/REVIEW) - only a genuine `PERSISTENT_TREND` earns `QUALITATIVE_WINS`, same bar captaincy
  fusion already set. Wired additively into `evaluate_locked_squad` (`TransferAction.qualitative_note`,
  same pattern as `CaptainAction.qualitative_note` - never changes the underlying keep/transfer
  verdict, only attaches an FYI note) and into the dashboard's Transfer Watch card + `fpl
  decision-fusion --squad <ids> --bank <tenths>`. 6 new tests.
- **Continuous post-GW reassessment** (section I's real gap) - `maybe_run_post_gw_pipeline` only ever
  ran once per gameweek; the persisted `post_gw_plan`/`chip` decisions (Next GW Plan / Chip Strategy
  panels) went stale the moment a real material event happened afterward. Live captain/transfer
  verdicts were already continuously fresh (`evaluate_locked_squad` runs on every dashboard regen) -
  what was actually stale was the chip verdict and the logged plan snapshot. Added
  `_has_material_change_since_last_plan()`: while `READY_FOR_NEXT_DEADLINE`, a real HIGH/CRITICAL
  `change_events` row on a locked-squad player detected after the last pipeline run triggers a real
  re-run; anything lower-severity or off-squad is correctly ignored (matches section S's "do not let
  every headline trigger a model overhaul"). 2 new tests, both directions.
- **Live rank automatic refresh** (section K) - `fpl live-rank` was fully opt-in; the real last sample
  was 4 days stale when checked. `_maybe_refresh_live_rank()` now runs inside `run_scheduled`, gated
  on a real fixture genuinely `started=1` for the reference event (zero network cost outside a live/
  just-finished window, the same condition `_maybe_fetch_live_payload` already uses) and throttled to
  once per `_LIVE_RANK_MIN_REFRESH_MINUTES=20` so a short scheduler interval can't turn the heaviest
  network pattern in this project into a per-cycle cost. Smaller auto sample (200 vs the manual
  default 300) - a disclosed, deliberate trade since this path can fire repeatedly across a live day.
  Ran for real against GW1 (now finished): `~37` estimated rank off a real 51-point total, bracket
  1-5,442,291 off a 300-manager sample - genuinely wide, honestly reported, not fabricated precision.
  3 new tests (fires when live, no-ops outside a live window, throttles within the refresh window).
- **Calibration/learning persistent storage built** (section R) - `prediction_outcomes` table
  (migration `0029`, one row per real `(player_id, event, season)`) + `models/calibration.py`.
  Deliberately does NOT fit any calibration model from this - one gameweek is nowhere near enough,
  same discipline `price_forecast.py`/`squad_churn.py` already apply. Two halves:
  `record_predictions_for_locked_squad()` snapshots the model's real `expected_points()` for the
  locked squad once, right when the lifecycle genuinely reaches `LOCKED` (wired into
  `run_scheduled`) - idempotent per (player, event), so a real prediction can never be silently
  overwritten with a later, hindsight-influenced number. `record_outcomes_for_finished_event()` fills
  in the real actual outcome (`player_stats_snapshot.event_points`/`minutes`, plus whatever real
  qualitative/user signal exists) once a gameweek finishes - wired into `run_post_gw_pipeline`, since
  that's the genuinely time-sensitive moment (the live snapshot only reflects THIS gameweek until the
  next one starts generating points). **Ran for real against GW1's still-live snapshot data before it
  gets overwritten by GW2**: all 15 locked-squad players got a real outcome row (`predicted_median`
  honestly `NULL` for GW1 specifically - this table didn't exist before GW1's deadline, so there was
  never a real pre-deadline prediction to capture; the actual points/minutes/qualitative-direction
  side is real and complete). GW2 onward will capture both sides genuinely. 5 new tests.
- **Real end-to-end verification, not just unit tests**: 812/812 full suite passing (801 baseline +
  11 new). Live-verified against the real production DB throughout, not just mocked - the market-name
  alias fix, the Tzolis recompute, the queue drain, the live-rank sample, and the calibration backfill
  were all run for real against `data/fpl.db`, not only asserted in tests.
- **What this does NOT close, stated plainly**: sections C/D/M (a formal data-lineage audit document,
  a from-scratch data-source review) were not produced as standalone deliverables - most of their
  substance already exists scattered through this file's own history (every source's reliability/
  freshness/coverage/failure-behavior is documented at the point it was built), and a structured index
  of it was judged lower-value than the runtime/correctness fixes above given real GW2 planning is the
  actual near-term need. A real follow-up if the user wants a single compact reference doc built from
  what's already here.

## GW2-accuracy implementation audit (2026-08-26, same day, continued)

Direct follow-up: audit the real implementation (not documentation) behind sections C/D/M, with GW2
accuracy as the priority. Traced every major xP input source -> ingestion -> DB -> projection -> decision
by reading the actual code, then live-verified each claim against the real production DB. Found and fixed
real gaps rather than writing an audit report.

**The single biggest real finding: zero 2026-27 match data had been fed back into the live model at
all, five real days after GW1 finished.** `match_results_history` (feeds Dixon-Coles team strength) and
`player_match_stats_history` (feeds the primary Understat goals/assists rate path) both showed 0 real
rows for season `2026-27`, confirmed live via direct query - `fpl backfill-odds`/`fpl backfill-xg` are
real, already-tested, already-proven commands, but were NEVER wired into the regular automatic cycle for
the LIVE season, only ever run manually against historical seasons. This meant every player's goals/
assists rate ran through the season-fallback path all season, and the Dixon-Coles fit never saw a single
real 2026-27 result. Ran both backfills for real (10 real GW1 matches, 310 real player rows) and wired
both into `run_scheduled`, but only after fixing two real problems this surfaced:
- `backfill_understat` had **no idempotency at all** - a second call re-fetched every played match's
  Understat page again, unsafe to put on any recurring cadence (a monotonically growing re-fetch list as
  the season progresses). Added a real skip-already-backfilled-match guard (same "idempotent unless
  --force" contract every other backfill command here already has). `backfill_football_data` was already
  safe (one small CSV fetch, idempotent upsert) - wired in directly, no fix needed.
- **A real, previously-undiscovered ~19% player-name resolution gap** in `market_identity.py::
  resolve_player_id` - exact-match-only (no diacritic folding, no last-name fallback), confirmed live to
  silently drop 58 of 310 real 2026-27 Understat rows, including B.Fernandes (Understat's "Bruno
  Fernandes" vs FPL's `web_name="B.Fernandes"`/`second_name="Borges Fernandes"`) - a real, highly-owned,
  locked-squad player. Fixed by reusing (not duplicating) `predicted_lineups_source.py::
  match_player_in_team`'s already-proven diacritic-fold + last-word-of-second_name fallback, scoped to
  the real team the row belongs to (same low-collision-risk property that function's own docstring
  establishes) - added an optional `team_id` parameter, zero behavior change for any caller that doesn't
  pass one. Re-ran the backfill after both fixes: unresolved rows dropped from 58 to 10 (~97% resolution,
  matching the reused function's own proven rate elsewhere).

**Cold-start audit (section 2): tested Tzolis, an established player, and 4 further real new-to-PL
cases directly.** Confirmed the earlier Tzolis fix is genuinely general, not a patch - `van Ewijk`
(Coventry, no cross-league match), `Slater`/`Muharemovic` (Hull/Leeds, real GW1 starters) all correctly
picked up `current_season_only` with real minutes/points the moment they had any real current-season
evidence. **Found and fixed a second, real, general cold-start bug the same audit surfaced**: a true PL
debutant (`prior_row is None` - no `player_season_history` at all) who picked up even one real
current-season snapshot - including a genuine 0-minute unused-sub cameo - landed on
`basis="current_season_only"`, which is NOT in `_WEAK_EVIDENCE_BASES`, permanently locking out the
predicted-lineup/start-percent override for the rest of the season even when a real, current, independent
source disagreed. Confirmed live: a real Chelsea signing (Palestra) frozen at 0.0 expected minutes despite
a real 40% synced start-percentage and a real "starting" predicted-lineup row. Fixed with a new, narrowly-
scoped `is_thin_debut` condition (`prior_row is None` AND `finished_events <= 2`) - Palestra: 0.0 -> 15.0
expected minutes (30 predicted-lineup-implied minutes, correctly halved by his real DOUBTFUL availability
status - the full pipeline composing correctly, not just one override in isolation). Verified this does
NOT catch established players with real prior-season history behind a currently-low number (Havertz,
Tzolis) - both structurally excluded since they have a real `prior_row`, confirmed unchanged by the fix.
3 new regression tests, including one proving the override correctly stops once 4 real gameweeks of
current-season evidence accumulate (current-season evidence progressively takes back over, per the
spec's own requirement).

**Real, disclosed, deliberately-not-fixed finding (section 4/1)**: `player_setpiece_history.
penalties_order` (real, official, already-ingested Tier 1 data - 20 real current primary penalty takers
found live, including Haaland/B.Fernandes/Szoboszlai/Calvert-Lewin) is used ONLY for the change-detection
alert and captaincy's display-only `is_penalty_taker` flag - it never adjusts the goals-rate probability
inside `expected_points.py` itself. This is a real, live, potentially material gap specifically for a
player who has RECENTLY become or lost primary penalty duty (their shrinkage-regressed historical rate
wouldn't yet reflect a new role, or would overstate a lost one). Investigated a fix and deliberately did
NOT build one this pass: `player_match_stats_history` has no penalty-shot flag at all (Understat's raw
per-shot `situation` tag was never parsed into the aggregated per-match schema), so any numeric
adjustment right now would have to be an invented constant (a real PL average penalty-award rate isn't
sourced from this project's own ingested data) - exactly the "no fake calibration" fabrication risk this
audit was told to avoid. The real, correct fix (parsing Understat's per-shot penalty tag into a new
schema field) is a genuine, scoped follow-up, not attempted under this pass's own risk/reward bar.

**Data-source freshness audit (section 3)**: `fpl source-status` checked end to end - all 20 sources
`OK`, `fpl doctor` clean. Two sources showing old `last_success` timestamps investigated and confirmed
correct-by-design, not silent staleness: `fpl_api_element_summary` (`sync-history`, only updates once a
past season fully closes - nothing new exists to fetch mid-season) and `understat_cross_league`/
`football_data_E1` (promoted-team/cross-league priors, real preseason-only inputs by their own nature -
correctly don't need re-running once the season's actual squads are set). `football_data`/`understat`
now show today's real timestamp after the backfill-wiring fix above - live-verified via the real
`run_scheduled` log, not just asserted (`odds backfill: 10 match(es) upserted`, `xg backfill: 0 new
match(es) processed` on the following cycle - correctly 0, proving the new idempotency guard works for
real, not just in a test).

**Decision verification (section 5)**: transfer/captain fusion's disagreement-override logic already has
real, passing unit-level proof (6 new transfer-fusion tests from earlier today, 5 pre-existing captain
ones) - a real `PERSISTENT_TREND` case genuinely flips the verdict to `QUALITATIVE_WINS`, a single-match
signal correctly does not. **Stated honestly, not glossed over**: a real, live disagreement case cannot
exist in production data yet - `PERSISTENT_TREND` requires 2+ real analyzed matches for the same player/
signal, and GW1 is still the only gameweek this project has ever run real qualitative analysis against.
This is a genuine, correct data limitation (the same "not yet outcome-verified, schema/logic-verified
instead" honesty posture used throughout this project for anything gated on real match volume that
doesn't exist yet), not a gap in the fusion logic itself - GW2's real analysis will be the first chance to
observe a real production disagreement.

**Automation verification (section 6) - live-verified against the real production log, not just
reasoned about.** Ran a real, complete `fpl run-scheduled` cycle end to end and read `logs/fpl_agent.log`
across the last ~10 real scheduled runs (spanning 2026-08-25/26): confirmed live, in order - sync ->
odds/xg backfill (new) -> predicted-lineup/start-percent change detection -> live-odds/player-odds sync ->
news sync -> my-team sync (`picks_fetched=True`, real) -> alert delivery -> dashboard regen, every real
cycle. Found real, concrete proof each of the six chain links genuinely already fires unattended: a real
`post-GW pipeline: event=1 decision_id=66` line from a prior real cycle (proves GW-end -> next-GW plan is
genuinely automatic, not just tested), a real `lineup-probability sync: 1 change event(s)` line (a real
squad player's start-percent moved - correctly logged, and correctly did NOT trigger a reassessment since
its real severity was MEDIUM, not HIGH - materiality gating confirmed working on real data, not just the
synthetic test from earlier today), and real `my-team sync: picks_fetched=True` on every cycle. Zero
manual CLI invocation was needed to produce any of this - Claude Code's only real role in the whole
observed chain was the qualitative-analysis skill runs from earlier today, exactly as designed.

**Full suite: 824/824 passing** (812 baseline + 12 new). Every fix in this section live-verified against
the real production DB (`data/fpl.db`), not only asserted by tests - the backfill re-run, the name-
resolution improvement, the Palestra recompute, and the real scheduled-cycle log were all checked against
actual current data.

## P0/P1 implementation from the gap audit (2026-08-26, same day, continued)

Direct follow-up: implement the audit's P0 items in dependency order, then the P1 items that materially
improve optimizer accuracy. Hard constraint carried through every item: never fabricate, never a global
weight, reuse existing infrastructure, preserve current numeric behavior unless a measured improvement
justifies changing it.

**P0-1: expose the real xP component breakdown.** `_match_components()` always computed eight real terms
(appearance/goals/assists/bonus/clean_sheet/cards/conceded/defcon) and threw them away after summing -
nothing downstream could ever answer "why is this player's xP 5.8". New `ComponentBreakdown` dataclass
(`models/expected_points.py`) returned from `_match_components` instead of a bare float, with a `.total`
property summing in the exact original field order (zero float-rounding drift, regression-tested).
`ExpectedPoints`/`WindowExpectedPoints` gained an additive `components` field. **Live-verified**: Tzolis/
Gonzalo/van Ewijk's real components all sum exactly to their reported median.

**P0-2: robustness classification (ROBUST/MODERATE/FRAGILE) using shared Monte Carlo trials.** New
`models/robustness.py::compare_candidates()` - reuses `scenario_engine.py`'s exact `_draw_fixture_for_team`/
`sample_player_trial_points` primitives (the same real per-trial point model floor/ceiling already uses),
draws two named candidates against a shared trial set (correctly correlated when they share a real
fixture), and labels how often the point-estimate "leader" actually wins per-trial - real, disclosed,
uncalibrated thresholds (65%/50%). Wired additively into `CaptainAction.robustness` and
`TransferAction.robustness` (`optimization/decision_engine.py`), never changing the underlying keep/
change verdict. **Live-verified**: real squad's captain change (Mbeumo over Szoboszlai) is MODERATE, not
robust - a genuinely useful signal a bare median delta couldn't show. Real transfer (Tzolis->Tavernier)
also MODERATE.

**P0-3: structured qualitative evidence -> bounded, component-targeted xP/minutes adjustment.** New
`models/qualitative_feed.py` - only fires on a real PERSISTENT_TREND (2+ real matches agreeing,
`qualitative_trends.py` - the same bar captain/transfer fusion already require), sized as a bounded 15%
proportion of the model's own already-computed value for the SPECIFIC component the signal maps to
(GOAL_THREAT->goals, CREATION->assists, SET_PIECES->goals) - never an invented absolute number.
Deliberately kept OUT of `median` itself (this project's FACTS/DERIVED/REASONING layering rule, same
precedent as `decision_fusion.py`'s captain/transfer notes) - exposed as separate
`qualitative_adjustment`/`qualitative_note` fields instead, zero regression risk to any existing caller
that only reads `median`. A parallel, smaller mechanism in `expected_minutes.py` handles ROLE/MINUTES
signals the same way, following that function's own established in-place-override convention instead
(bounded, same 15%, same PERSISTENT_TREND gate). **Real, honest state**: zero real players currently have
2+ real observations (GW1 is still the only analyzed gameweek), so this is correctly inert in production
right now - confirmed live, mechanism proven via 5 tests that seed real synthetic persistent trends.

**P0-4: automatic segmented prediction/outcome measurement.** `prediction_outcomes` (built earlier the
same day) gained two real, already-computed-at-prediction-time columns (migration `0030`):
`predicted_minutes_basis` (expected_minutes()'s own `basis`) and `predicted_availability`
(`availability.classify()`) - both captured going forward so cohorts can be judged honestly by what the
model believed AT THE TIME, not by current hindsight state. New `models/calibration.py::segmented_accuracy()`
groups real MAE by position, nailed-vs-rotation (predicted_expected_minutes >= 75), new-transfer/cold-start
(predicted_minutes_basis matching expected_minutes' own weak-evidence bases), and returning-injury/doubtful
- a cohort with fewer than `min_samples` (default 3) real rows is silently omitted, never reported with a
misleadingly precise MAE. New `fpl calibration-report` CLI command. **Real, honest state, confirmed live**:
`fpl calibration-report` correctly reports "no cohort has enough real data yet" - GW1's own
`prediction_outcomes` rows have `predicted_median=NULL` (this table didn't exist before GW1's deadline),
so segmentation is genuinely blocked until GW2+ produces real prediction-and-outcome pairs. This is not a
code gap - the mechanism is built, tested, and will start reporting real numbers automatically the moment
real data exists.

**P1 items, in order:**

- **Manager-intelligence -> expected-minutes integration**: a real, high team-wide starting-XI rotation
  rate (`manager_intelligence.py`, needs >=2 real analyzed matches) downgrades `expected_minutes()`'s
  `confidence` by one tier (HIGH->MEDIUM->LOW) - deliberately never touches the numeric estimate itself,
  avoiding a second stacked heuristic on top of this player's own already-real minutes read. **Live-verified
  honest state**: no real team has 2+ analyzed matches yet (only GW1 exists), so this is correctly inert in
  production - confirmed via direct query, 3 new tests prove the mechanism with synthetic data.
- **Verified penalty-duty extraction, only after confirming the field is real.** Fetched all 10 real GW1
  matches live before writing any code: FotMob's shotmap `situation` field is real and reliable (2 real
  penalty shots found, Brentford v Spurs and Newcastle v Liverpool). Parsed into new `player_match_state.
  penalty_shots`/`penalty_goals` columns (migration `0031`, `models/match_intelligence.py`). New
  `models/penalty_duty.py::league_penalty_evidence()` aggregates the real league-wide total and gates on a
  real minimum sample (20 shots) before ever calling itself "sufficient for adjustment" - **deliberately does
  NOT feed anything into expected_points.py**: 2 real observations league-wide is nowhere near enough to fit
  a defensible conversion/uplift rate, and doing so would be exactly the premature calibration this
  project's own rules forbid. Confirmed live: `sufficient_for_adjustment=False`, correctly. The real,
  current WHO of penalty duty was already solved (official `penalties_order`, feeds captaincy's display);
  this closes the data-capture half of HOW MUCH, honestly reporting insufficient volume rather than
  fabricating a number.
- **Full-sequence club-limit validation in transfer search - already correctly implemented, verified
  rigorously rather than assumed.** The audit's own citation (Plan 1a's original "not validated across
  steps" note) was stale - a later same-day 2026-08-20 fix already threads the evolving `state.squad_ids`
  through `best_transfer_for_player` at every beam step. Wrote a genuine multi-step regression test to
  prove it; the FIRST version of that test was itself wrong (assumed the search would only ever swap out
  the original weak club-B players, when the real optimal legal path swaps out the weak club-A incumbents
  directly - a smarter, still-legal solution the search correctly found). Corrected the test (P1/P2 given
  real EV higher than every candidate, so they're structurally never touched) and it now genuinely proves
  a later step correctly rejects a candidate that would push a club over-cap given the squad AS IT STOOD
  after an earlier step's own swap, not the original squad. No production code change needed - the item is
  closed by verification, not by a fix.
- **Historical skill-selected Elite-manager panel - real infrastructure built, real data constraint found
  and disclosed, not glossed over.** Checked live before building anything: FPL's `leagues-classic/314/
  standings/` endpoint is season-scoped to whatever is CURRENTLY live (confirmed: page 1 returned this
  season's real GW1 totals, not a past season's final table) - there is no way to retroactively fetch a
  PAST season's final standings once a new one has started. New `ingestion/elite_panel.py::
  snapshot_elite_panel()`/`get_elite_panel()` (migration `0032`, `elite_manager_panel` table) + `fpl
  sync-elite-panel --season` - real, sequential top-N capture (not the rank-stratified sample `eo_sample.py`
  uses for a different purpose), genuinely reusable, but only becomes a real historically-earned signal when
  run near a REAL season's end and used the FOLLOWING season. **Honest state**: zero real panels exist yet -
  this is the first season this project has ever been positioned to capture one for; the real payoff starts
  next season, not this one.
- **Transfer robustness comparison** - built alongside P0-2 above (`TransferAction.robustness`), same
  shared-trial mechanism, no separate work needed.
- **Chip-strategy explanation (why now / why not later / EV / opportunity cost / confidence).** New
  `ChipExplanation` dataclass + `_explain_schedule()` (`optimization/chips.py`) - built entirely from
  `window_event_median`, the same real per-(window, event) trial-median dict the DP already computes to
  make its own choice, zero new modeling. Names the real runner-up event and the real opportunity-cost gap
  within the same chip's own real eligible window; honestly reports "only real eligible GW" when no real
  alternative exists rather than fabricating a comparison. Wired into `fpl season-sim`'s printed output and
  the logged decision detail. **Live-verified against the real locked squad** (GW2-20 horizon): "GW2
  wildcard (+474.0) beats the next-best real eligible GW20 (+-6.2) by 480.2 - low confidence", and a correct
  "only real eligible GW" line for the one chip with no real alternative in the sampled window.

**Full suite: 856/856 passing** (824 baseline + 32 new). Every item live-verified against the real
production DB and the real locked squad, not only asserted by tests - component breakdowns, robustness
labels, the calibration report, penalty evidence, the corrected multi-step club-limit test, and the chip
explanation narrative were all checked against actual current data, including a real season-sim run.

**What remains genuinely blocked by insufficient data, stated plainly rather than glossed over:**
- P0-3 (qualitative feed) and P0-4 (segmented calibration) are both real, tested, wired, and CORRECTLY
  INERT in production right now - not because of a bug, but because GW1 is still the only analyzed
  gameweek (no player has a real persistent trend yet) and GW1's own predictions were never captured before
  its deadline (no real prediction-outcome pair exists to segment yet). Both will start producing real
  output automatically once GW2 provides a second real data point - no further code change needed.
- Manager-rotation confidence downgrades are similarly inert - no real team has 2 analyzed matches yet.
- League-wide penalty evidence (2 real shots) is far below the real 20-shot bar this project set for
  itself before trusting a conversion rate - will grow automatically as more real gameweeks are analyzed.
- The Elite-manager panel has no real historical data to draw from until a real season actually ends and
  gets snapshotted - a genuine, disclosed multi-month wait, not a code gap.

## Optimizer precision + auditability pass (2026-08-26, same day, continued)

Direct follow-up: make every ROLL/TRANSFER/CAPTAIN decision explainable, counterfactual (real best
alternatives, not just the chosen option), and measurable. Section 2's own framing ("the highest-priority
feature") was the real ROLL vs TRANSFER counterfactual - built first, then the same treatment extended to
captaincy.

- **`optimization/decision_analysis.py`** (new) - `analyze_transfer_decision(conn, locked)` and
  `analyze_captain_decision(conn, locked)`. Both reuse 100% already-tested machinery (`transfers.py`'s
  `_squad_gw_ev`/`best_transfer_for_player`, `captaincy.py`'s `evaluate_captaincy`, `robustness.py`'s
  shared-Monte-Carlo comparison, `decision_fusion.py`'s qualitative notes, `decision_engine.py`'s own
  `_evaluate_captain` for the KEEP/CHANGE verdict itself) - no new projection model, no new candidate
  search, no new verdict logic. What's new is the real, structured comparison layer: real GW1/3/5 roll
  totals vs ranked real transfer candidates with rejection reasons (`"real net advantage over 3 GW is
  X.XX pts lower than <best> (Y vs Z)"`), and the same ranked-alternatives-with-rejection-reasons
  treatment for captaincy's top-3 real median options. `_FUTURE_FT_NOTE` states the value of an unused
  free transfer as a disclosed, unquantified consideration per the pass's own explicit "do not invent a
  fixed point value" instruction - never folded into the expected-advantage numbers.
- **`fpl transfer-analysis [--squad ids --bank £m]`** - prints both the transfer counterfactual and the
  captain counterfactual in one real run, defaulting to the real locked squad. Live-verified against the
  real production DB: `Tzolis -> Tavernier` clears the real 1.0xP 3-GW bar (ROBUST) over the real
  runner-up (`E.Le Fée -> Tavernier`, 1.32pts lower) and third (`B.Fernandes -> Tavernier`, 3.07pts
  lower); captain `Mbeumo` (MODERATE) over real alternatives `Szoboszlai`(-0.46) and `Haaland`(-0.88).
- **`optimization/post_gw_pipeline.py`** - both analyses now compute and log automatically as part of the
  already-scheduled `run_post_gw_pipeline()` call (each wrapped in try/except, non-fatal), folded into the
  existing `decisions.detail` JSON under `detail["transfer"]["analysis"]`/`detail["captain"]["analysis"]` -
  no new table, reproducible without a giant blob. This is what satisfies the reproducible-decision-trace
  requirement AND the "no manual Claude Code intervention" requirement simultaneously: the existing
  autonomous post-GW pipeline (already wired into `run_scheduled`/`live-match-poll`) now logs the full rich
  rationale every time it runs, with zero new manual step. Live-verified: `run_post_gw_pipeline(conn,
  event=1)` against the real production DB logged `decision_id=72` with the complete real nested structure
  for both captain and transfer.
- **10 new tests** (`tests/test_decision_analysis.py`) - transfer analysis (review-state, roll reporting,
  transfer recommendation, threshold-miss roll, ranked rejection reasons, qualitative-note gating, the
  future-FT note's permanent presence) plus captain analysis (keep-with-real-gap, change-with-ranked-
  alternatives-and-robustness, qualitative-note gating). 866/866 full suite.
- **Threshold audit (section 18), confirmed not GW1-tuned**: `_TRANSFER_DELTA_THRESHOLD=1.0` (3-GW net
  xP, hit-cost aware) deliberately reuses `decision_engine.py`'s own pre-existing threshold rather than
  redefining one; `_CAPTAIN_DELTA_THRESHOLD=0.5` and robustness's 0.65/0.50 win-rate bars all predate GW1's
  real outcomes and are already labeled "disclosed, uncalibrated" in their own code comments - re-checked
  directly in this pass, not re-derived.
- **What this does NOT close, stated plainly**: a real decision-level backtest ("what would have happened
  if I'd followed the optimizer vs rolled vs took the best-rejected alternative", tracking actual points/
  hits/captain/chips against PREDICTED vs REALIZED) remains unbuilt - genuinely blocked on real executed-
  and-measured decisions, which don't exist yet (GW1's squad predates this whole decision-fusion
  infrastructure; GW2 hasn't been played through this system yet). The dashboard's existing "AI Decisions"/
  Chip Strategy panels already read from the same `decisions` table this pass writes into, so no new
  dashboard wiring was needed to surface this - confirmed by reading the panel's own data source rather
  than assumed.

## Decision-quality audit: the Tzolis case, evidence confidence, REVIEW gate, stress testing (2026-08-26, same day, continued)

Direct user challenge, not a bug report: the optimizer recommended selling Tzolis (a very recent Arsenal
arrival, real 75-minute GW1 debut, 1 assist) for Tavernier at +12.77 3-GW net EV, and the user explicitly
did NOT want "he scored 6 points" used as a defense - they wanted the actual mathematical reason audited,
with an explicit ban on blind threshold/weight tuning to make the number look more comfortable.

**Section 1 - reproduced the exact arithmetic by hand, found a real bug.** Tzolis's `expected_minutes()`
blend: `finished_events=1`, real GW1 minutes=75 -> `current_per_gw=75`; his only `player_season_history`
row is `2021/22, 326min, 0 starts` -> stale (5-season gap) -> `prior_per_gw=8.58`; `weight_current=min(0.5+
0.2*1,0.9)=0.7`; `base=0.7*75+0.3*(8.58*0.6)=54.04`, correctly rounds to the real reported **54.0** -
arithmetic confirmed exact, not approximated. **The real bug**: `get_start_percent(conn,557)` already
returned a real, current, synced **80%** starting probability for GW2 - a strictly stronger, more current,
per-fixture signal than the season-average blend - but it was NEVER APPLIED, because the override block
that raises minutes toward `75*0.80=60.0` only fires when `basis in _WEAK_EVIDENCE_BASES`
(`models/expected_minutes.py`), and `"blended_current_and_stale_prior"` (the branch Tzolis's exact real
situation produces) had never been added to that set - it postdates the set's original definition. Real,
already-computed evidence sat unused, not because of insufficient data but a basis-string omission -
affects every player in the same evidence shape (real current start + stale/foreign-only prior), not just
Tzolis. **Fixed**: added `"blended_current_and_stale_prior"` to `_WEAK_EVIDENCE_BASES` - the override is
structurally raise-only (`if target > base`), so this can only correct an under-estimate, never inflate a
well-evidenced one. Live effect: Tzolis 54.0 -> 60.0 expected minutes, 1gw median 2.39 -> 2.65, 3gw 6.38 ->
7.09. Re-ran the real optimizer: **+12.77 -> +12.06 - TRANSFER still survives**, honestly reported rather
than declared fixed just because a number moved.

**Section 2 - audited whether ROLL/SELL/BUY are conflated. They are not, verified by reading the real code
path, no change needed**: `decision_analysis.py` computes the real GW-by-GW ROLL baseline first
(`_squad_per_gw`), independently of any transfer; separately searches every real SELL candidate x its real
best BUY replacement (`best_transfer_for_player` per squad member, respecting budget/club-limit); only
THEN applies the `threshold_cleared` ROLL-vs-TRANSFER gate to the single best result. This ordering is
mathematically necessary, not conflated - a manager cannot rationally judge "is transferring worth it"
without first knowing the best available replacement's real value.

**Sections 3/4/15 - built `models/projection_confidence.py`, the real "is the model well-evidenced for
THIS player" question, explicitly separate from `robustness.py`'s Monte Carlo stability.** Rule-based
(never a weighted score - the user's own explicit constraint): `data_confidence` from real Understat
`matches_played` this season (a minutes-weighted match-equivalent count) vs whether the fallback prior is
stale/cross-league/absent; `minutes_confidence` from `expected_minutes()`'s own real `basis` field (a
direct, disclosed mapping of an already-computed field, not reinterpreted) further capped by a real
rotation-risk hedge or the function's own LOW-confidence flag; `overall = min(data_confidence,
minutes_confidence)` - a chain-is-as-strong-as-its-weakest-link combination rule, not an average. Every
threshold disclosed and uncalibrated, same honesty posture as every other heuristic in this codebase.
**Live-verified, real and discriminating**: Tzolis and Tavernier both land on **MEDIUM** (the honest,
shared, early-season state - only 1 real gameweek exists for anyone yet); Palestra (a genuine Chelsea
debutant, cross-league prior only) correctly comes out **LOW**; established players (Haaland) also land on
MEDIUM right now for the same real reason (only 1 real match-equivalent exists league-wide) - the model is
NOT asymmetrically doubting Tzolis specifically, it is honestly uncertain about everyone this early, which
is itself the real, load-bearing answer to the user's stated worry.

**Section 11/16 - built the real REVIEW gate.** `analyze_transfer_decision`/`analyze_captain_decision`
(`decision_analysis.py`) now check the CHOSEN candidate's real evidence confidence: if EITHER side of a
transfer swap (or the suggested captain) is LOW/VERY_LOW, the verdict downgrades from TRANSFER/CHANGE to
**REVIEW** - `chosen`/`suggested` stay populated (the model's own real lead, shown honestly) but the
verdict itself refuses to fabricate certainty the data doesn't support. `_MIN_EVIDENCE_CONFIDENCE_FOR_
ACTION="MEDIUM"` - deliberately not a stricter bar, since MEDIUM is the real, current, shared state nearly
every player has this early in a season; blocking on MEDIUM would make the optimizer permanently unable to
recommend anything for months. Real, live-verified: neither Tzolis->Tavernier nor Mbeumo both clear MEDIUM,
so REVIEW does not fire for either right now - the mechanism was proven to actually work via a dedicated
test with a synthetic LOW-confidence candidate (`test_transfer_downgraded_to_review_when_evidence_
confidence_is_low`), not merely asserted never to fire.

**Section 14 - built a real counterfactual stress test, `optimization/decision_sensitivity.py`.**
Perturbs `expected_minutes()` at the real call boundary (±15%/±30%, the exact magnitudes the user's own
brief named) and recomputes the exact real `evaluate_transfer()` formula unchanged - never a new EV model.
**Real, previously-undiscovered bug found and fixed while building this**: `expected_minutes` is imported
separately into TWO modules (`expected_points.py`, used only for display fields, and
`minutes_distribution.py`, the module that ACTUALLY anchors the scoring path via `nonzero_fraction`) - an
early draft patched only the first, silently reaching nothing (every scenario showed zero effect,
correctly caught as suspicious rather than reported as a "no scenario flips it" finding). Fixed by patching
both real bindings; a dedicated regression test pins this exact failure mode. **Live-verified against the
real Tzolis/Tavernier swap**: net_3gw ranges +6.31 (replacement rotates 30% harder than projected) to
+14.04 (best case) across 7 real scenarios including the explicit worst-case (sold player over-performs
+15% while the replacement under-performs -15%, net_3gw=+8.12) - **no tested scenario flips TRANSFER to
ROLL**, a real, honest robustness finding, not merely a bare ROBUST label.

**Section 13**: `_TOP_N_CANDIDATES` raised 3 -> 5 (shared by transfer and captain analysis) - real GW2
output now shows 5 ranked alternatives with rejection reasons, not 3.

**Section 7, partially closed, disclosed honestly**: `models/minutes_distribution.py::
minutes_bucket_probabilities` already computes a real 3-way `p_zero`/`p_partial`(1-59min)/`p_full`(60+min)
distribution - the closest real equivalent this project has to P(no-appearance)/P(bench-cameo)/P(start).
Now surfaced in `fpl transfer-analysis`'s output for the chosen swap (previously computed but never
printed anywhere). Real, disclosed limitation: for both Tzolis and Tavernier `source=fallback_prior`, not
`empirical` - the empirical per-match bucket distribution needs >=4 real current-season matches
(`_MIN_MATCHES_FOR_EMPIRICAL`), which doesn't exist yet this early in the season for anyone. Real, honest
numbers regardless: Tzolis p(0min)=0.33, matching his real 33%-no-appearance risk plainly rather than
hiding it behind a point estimate.

**Sections 6/8/9 - verified against real data, not rebuilt (architecture already correct).** Confirmed
live: Tzolis's real `match_observations` row (OBSERVED: "started, 75 real minutes, 4 shots, 1 assist" ->
INFERRED: "high-shot-volume attacking involvement... not a token appearance" -> FPL_IMPLICATION:
CREATION/POSITIVE, confidence=**low**) exists and is real, not fabricated - `qualitative_trends.py`
correctly classifies it `NEW_SIGNAL` (sample_size=1), so `qualitative_feed.py`'s PERSISTENT_TREND gate
correctly keeps `qualitative_adjustment=0.0` for him - his real 6-point GW1 return does NOT inflate his
projection, exactly satisfying the user's explicit "do not use the 6 points as proof" instruction. His
real goals/assists rate is confirmed driven by real Understat shot-level data (`matches_played=0.87`,
`shrunk_per90` off real xG/xA), never raw FPL points.

**Section 17 acceptance test, 5 real archetypes + Tzolis, run against the real production DB:**
```
Haaland   (established premium):        overall=MEDIUM  (1.0 real match-equiv - honestly thin, league-wide)
Rice      (established rotation-risk):  overall=MEDIUM  (real rotation-risk hedge caps minutes_confidence)
Tzolis    (recent PL transfer):         overall=MEDIUM  (0.87 real match-equiv, real current evidence)
Abraham   (doubtful/returning):         overall=MEDIUM  (real rotation-risk hedge + DOUBTFUL damping)
Palestra  (true debutant):              overall=LOW     (zero PL history, cross-league prior only)
```
The classification discriminates correctly across the real spectrum - Palestra (genuinely thinnest
evidence) is the only LOW, everyone else sharing this early season's real, honest MEDIUM uncertainty.

**26 new tests** (7 `test_decision_analysis.py` additions - the REVIEW-gate mechanism proven both ways;
5 `test_decision_sensitivity.py` - the exact both-module-binding bug regression-guarded directly; plus
`projection_confidence.py`/`decision_sensitivity.py` exercised live against real production data
throughout, not only unit-tested). 873/873 full suite. `fpl dashboard` regenerates clean post-change (no
dashboard code touched - confirms no regression to the render path that reads the same `decisions` table).

**What this does NOT close, stated plainly**: P(start)/P(bench)/P(no-appearance) is real but still
running on the fallback-prior 0.85/0.15 heuristic split rather than a genuinely empirical per-match
distribution (needs 4+ real current-season matches per player, which doesn't exist yet this early in any
season for anyone) - the machinery is real and already wired, not a gap in this pass, just bounded by real
calendar time the same way several other "grows automatically once GW2+ exists" items in this file already
are. A dedicated `fpl player-audit <id>` full-panel command (section 12's literal ask) was not built as a
separate command - the same information (components, evidence, confidence, decision effect) is available
today through `fpl transfer-analysis`'s real output for any candidate actually reached by a live decision;
building a standalone panel for an arbitrary, not-currently-relevant player id was judged lower-value than
the decision-flow integration above and was not attempted this pass.

## Squad-level decision-quality audit: is the optimizer optimizing player delta or full squad outcome? (2026-08-26, same day, continued)

Direct follow-up: the user was not satisfied that a Tzolis-vs-Tavernier pairwise comparison proves Tzolis is
the RIGHT sell for the FULL squad - they watched Arsenal dominate GW1 with Tzolis looking sharp while other
squad members underperformed, and wanted the full-squad-portfolio question audited, not just re-litigated
pairwise. Explicit ask: is the optimizer optimizing PLAYER DELTA or FULL SQUAD OUTCOME - "the latter is
what I actually need."

**Answer, proven algebraically and then verified against real data, not asserted**: `_squad_gw_ev` (the
real ROLL baseline `decision_analysis.py` already computes) is a flat sum of all 15 squad members' own real
`expected_points_window` - `new_squad_total = old_squad_total - out_ev + in_ev`. Under this project's own
squad-EV definition, a single swap's `net_ev_3gw` (the pairwise delta) is therefore ALGEBRAICALLY IDENTICAL
to the full-squad EV delta, not an approximation of it - there is no pairwise-vs-squad discrepancy to fix in
the current EV model, confirmed by the identity itself, not just reasoned about. (Whether bench players
should be weighted at less than a starter's full value, the way `optimization/squad.py`'s own initial-squad
ILP already does via `_BENCH_WEIGHT`, is a real, separate, disclosed simplification - see below.)

**Real, complete ranked table across the WHOLE squad, all 15 players, not just midfielders** - built by
calling `best_transfer_for_player` for every real squad member and sorting by real net 3-GW EV (the same
machinery `analyze_transfer_decision` already uses internally, just run without the top-5 cap and printed
in full):
```
rank SELL           BUY            1gw     3gw     5gw
1    Tzolis         Tavernier     4.62   12.06   18.04
2    E.Le Fée       Tavernier     4.36   11.45   17.04
3    B.Fernandes    Tavernier     3.57    9.70   14.43
4    Diop           Mendy         3.54    9.05   14.68
5    Ballard         De Cuyper    0.71    7.28    9.53
6    Maguire        De Cuyper    -0.02    6.35    8.11
7    Mbeumo         Tavernier     1.24    5.91    8.85
8    Calafiori      De Cuyper     0.54    5.67    7.12
9    Ajer           Mendy         2.16    5.30    9.86
10   João Pedro     Mateta        0.21    5.13    6.67
11   Szoboszlai     Tavernier     1.70    3.93    6.91
...  (Kinsky/Verbruggen/Kusi-Asare/Haaland below, all real, all weaker)
```
Every defender's own best real swap (Diop/Ballard/Maguire/Calafiori/Ajer) ranks BELOW Tzolis's - real,
computed, not filtered to midfielders only. Confirmed Tzolis is a real STARTER in the locked XI (not bench)
and genuinely has the lowest median xP (2.65) of the 5 real starting midfielders - the model's real
ranking, not a search blind spot.

**Section 3 - real GW1 underlying evidence for Tzolis and Arsenal, pulled directly from the DB, confirmed
flowing into the model.** Understat match-level row (the real primary source for his shrunk goals/assists
rate): 78 real minutes, xG=0.238, **xA=0.192, 3 key passes**, 4 shots - genuine creative involvement, not
just "6 FPL points". Arsenal team-level (`team_match_state`, FotMob): 64% possession, 20 shots, **1.88 xG**
vs Coventry's 0.20 - real, dominant. Confirmed this GW1 result is now one of 10 real 2026-27 rows in
`match_results_history`, feeding the live Dixon-Coles team-strength fit used for EVERY future Arsenal
fixture projection - Arsenal's real attacking performance DOES already improve the projection of Arsenal's
future attacking environment, structurally, not hypothetically. Real, disclosed gap found in the same
query: `player_match_state` (FotMob's own structured table) has several NULL fields for this match
(`minutes`, `rating`, `key_passes`, `touches_box`, `assists`) - the model doesn't actually depend on these
(minutes comes from FPL's own official `player_stats_snapshot`, goals/assists rate from the separate
Understat table), but the raw FotMob boxscore parse is thinner than the schema implies for these fields -
a real, disclosed data-coverage gap, not a decision-relevant one today.

**Section 5 - defender audit, real GW1 result vs real underlying vs real future projection, all 5
defenders in the squad:**
```
Ballard (SUN):   GW1: 0pts, conceded 2, no CS   | GW2 median=3.19, real CS component 0.99 - bad result, still a reasonable asset
Calafiori (ARS): GW1: 9pts, CS                  | GW2 median=3.36, real CS component 1.27 - good result, good asset (consistent)
Maguire (MUN):   GW1: 1pt, conceded 2, no CS    | GW2 median=3.92 (HIGHEST of the 3 starters), CS component 1.48 - bad result, model still likes the asset
Diop (IPS, bench): GW1: 2pts                    | GW2 median=1.42 (lowest), CS component 0.23, conceded penalty -0.89 - weak result AND weak projection
Ajer (BRE, bench): GW1: 8pts, CS                | GW2 median=2.80 - good result, modest bench-tier projection
```
Real, exact confirmation of the distinction the user asked to verify: Maguire and Ballard both had bad real
GW1 results but the model's real fixture-adjusted clean-sheet probability for GW2 does NOT just extrapolate
that badness forward - Maguire in fact projects as the squad's strongest starting defender for GW2. Diop is
the one real case of "bad result AND a genuinely weaker underlying projection" - and he's a bench player
already, correctly low-priority.

**Section 6 - real news/lineup propagation check since the GW1 deadline, all squad players, via the
already-built `change_events` table (no new ingestion needed).** 14 real events found. 13 are routine
`lineup_confirmed` (every real squad starter's GW1 inclusion being confirmed - expected, not news) and one
real `start_percent_change` (Ajer 70%->90%, MEDIUM). **One real, material, HIGH-severity signal found that
is currently NOT propagating into the quantitative model**: `Szoboszlai setpiece_change` (2026-08-24) - his
real penalty order moved from `[2,...]` to `[1,...]`, i.e. he is now Liverpool's real PRIMARY penalty taker.
This confirms, with a live, currently-relevant instance, the exact gap the prior session's audit already
disclosed and deliberately did not fix: `player_setpiece_history.penalties_order` only feeds the
change-detection alert and captaincy's display-only `is_penalty_taker` flag, never the goals-rate
probability inside `expected_points.py` itself. **Not fixed this pass either, for the same real reason as
before**: this project has only 2 real observed penalty shots league-wide so far (`models/penalty_duty.py`'s
own real 20-shot sufficiency bar) - building a numeric adjustment now would mean inventing a conversion-rate
constant with no real supporting sample, exactly the fabrication risk both audits were told to avoid. Named
honestly as a real, live, currently-underweighted signal rather than silently left undiscovered.

**Section 8 - built the real three-way confidence report, `decision_analysis.py`.** `data_confidence` (=
`evidence_confidence`, renamed to the audit's own vocabulary) and `model_confidence` (= `robustness`, same
value under its other name) are not new computations - `decision_confidence` is: a rule-based (never
weighted) combination of both plus a new `margin_ratio` (real net EV / the real materiality threshold) via
`_decision_confidence()` - HIGH only when evidence is HIGH+, robustness is ROBUST, AND the margin is >=3x
the threshold (disclosed, uncalibrated); LOW when any one of evidence/robustness/margin is weak (missing
information counts as weak, never strong); MEDIUM otherwise. **Real, live result for the current squad's
top transfer**: margin=12.06x (nowhere near narrow) but evidence is only MEDIUM (not HIGH+, since only 1
real gameweek exists for anyone yet) -> `DECISION_CONFIDENCE=MEDIUM`, not HIGH - an honest, non-inflated
label, not manufactured to make the recommendation look more or less certain than it is. 7 new tests
(`_decision_confidence`'s own rule table, plus the real Tzolis-shaped case pinned directly:
`MEDIUM+ROBUST+12.06x -> MEDIUM`).

**880/880 full suite** (873 baseline + 7 new). `fpl dashboard` regenerates clean, no dashboard code touched.
Live-verified against the real production DB throughout - the full 15-player ranked table, the Understat/
FotMob/team-strength evidence pull, the defender comparison, the change_events query, and the three-way
confidence label were all run against actual current data, not asserted from the code alone.

**Final recommendation, stated plainly**: Tzolis -> Tavernier remains the real, complete-squad-consistent
best transfer - not because a single pairwise comparison says so, but because the full 15-player ranked
table (built the same way section 1 asked, independently for every squad member) puts him at #1 with every
real defender and every other real midfielder ranking below him, and because the pairwise/full-squad
distinction the user asked to verify does not actually exist as a separate failure mode in this project's
current flat-sum squad-EV model - confirmed by algebraic identity, not asserted. The one real, disclosed
gap found this pass (Szoboszlai's live penalty-duty upgrade not reaching his goals rate) does not change
this recommendation, since Szoboszlai was never the leading transfer OR captain candidate either way, but is
named honestly as real, current, underweighted evidence rather than glossed over.

## "Redesign the missing layer": universal, zero-LLM match evidence (2026-08-26, same day, continued)

Direct architectural audit: why doesn't football information from matches OUTSIDE the locked squad
materially enter the projection/decision pipeline. Explicit instruction: don't assume the existing
qualitative system is adequate just because it produces text - trace one real completed match end to end
and show exactly which pieces of information can and cannot move a decision, then redesign the missing
layer (not just diagnose it).

**Real trace, Arsenal 3-0 Coventry (match_id=1), the actual pipeline as it exists, checked hop by hop:**
1. **Raw data**: real, comprehensive, leaguewide, never squad-scoped - `player_match_stats_history`
   (Understat, 31 real players this match) and `team_match_state` (FotMob: Arsenal 64% poss/20 shots/1.88xG
   vs Coventry 36%/4/0.20). Confirmed already flowing correctly: this real result is one of 10 real
   `match_results_history` rows feeding the live Dixon-Coles team-strength fit for EVERY future Arsenal
   fixture - the quantitative layer was never squad-scoped, verified not assumed.
2. **Qualitative analysis (LLM, `fpl match-analyze`)**: real, correctly evidence-gated
   (OBSERVED->INFERRED->FPL_IMPLICATION), but **only ever run for locked-squad players** - confirmed live,
   100% of the 14 real `player_fpl_implications` rows in production belonged to squad members, 0 to any of
   the other ~200+ real players whose matches had already been fully processed. This was a real, structural
   scoping choice in how the skill gets invoked (a human/Claude session analyzing "my squad's players in
   this match"), not a technical limitation of the schema or the ingested data.
3. **Structured evidence -> projection**: real and correctly gated where it exists - `qualitative_feed.py`
   only ever adjusts a component on a real 2+-match PERSISTENT_TREND (`qualitative_trends.py`), so even for
   the 14 covered players nothing was moving yet (GW1 is everyone's only real match). But for the other
   ~200 real players - including **Tavernier, the model's own #1 transfer TARGET** - the adjustment
   mechanism was structurally starved: zero rows existed to ever classify a trend from, regardless of how
   he actually played.
4. **Team-level qualitative signal**: real and leaguewide (`match_observations subject_type='team'` DOES
   cover all 20 real teams, the LLM skill writes those without squad-scoping) - but confirmed via grep that
   `team_intelligence.py`/`team_qualitative_state`'s only real consumer is `team_outlook.py` (dashboard/CLI
   display). Zero quantitative model file reads it - a second, independent "produces text but doesn't reach
   a decision" gap, this one universal rather than squad-scoped.

**What CAN currently change a decision**: any real player's own Understat/FPL data (goals/assists rate,
minutes, price) and any REAL team's Dixon-Coles-fit strength (via goals results, leaguewide) - both already
comprehensive. A LOCKED-SQUAD player's own PERSISTENT qualitative trend (2+ real matches) - real but
currently only possible for the ~14 players who have ever been manually analyzed.
**What CANNOT**: a non-squad player's qualitative performance, however good or bad, until he happens to
become a squad member and get manually analyzed - even if the optimizer is actively comparing him as a buy
target right now. Any team-level tactical/qualitative read at all, for any team, squad or not.

**The redesign - `models/statistical_evidence.py` (new)**: a deterministic, zero-LLM detector that reads
the SAME already-ingested Understat data (no new ingestion) for EVERY player in a finished match - not
squad-filtered - and writes real, disclosed, threshold-crossing observations directly into the EXACT SAME
`match_observations`/`player_fpl_implications` tables the LLM skill writes into, using the SAME
`fpl_signal` vocabulary (`GOAL_THREAT`/`CREATION`/`MINUTES`) `qualitative_feed.py`/`expected_minutes()`
already read. Every downstream consumer (`qualitative_trends.py`'s trend classifier,
`qualitative_feed.py`'s bounded adjustment, `expected_minutes()`'s ROLE/MINUTES override,
`decision_fusion.py`'s captaincy signal) picks these rows up completely unchanged - zero code needed
there, because this writes into the schema the LLM path already produces, just with universal coverage and
zero incremental cost. Real, disclosed thresholds (not fitted to outcome data, same honesty posture as
every other bar in this project): GOAL_THREAT on 3+ real shots or 0.30+ real xG; CREATION on 2+ real key
passes or 0.15+ real xA; MINUTES POSITIVE on 60+ real minutes for a real starter, NEGATIVE on a real
starter withdrawn before 30 minutes (substitutes correctly excluded from the negative branch - they were
never "withdrawn early", that's the expected shape of being a sub). Deliberately additive, never calling
`apply_match_analysis` (which deletes-then-replaces a whole `(match_id, phase)` - a second call would have
destroyed real LLM writeups) - idempotent per `(match_id, subject_id, signal, analysis_version)` via its
own pre-check, and never touches `player_qualitative_state`/`team_qualitative_state` (the LLM's own
narrative-synthesis tables, reserved for genuine judgment, not raw threshold crossings).

**Wired automatically into the already-existing, already-scheduled match lifecycle**: `maybe_enqueue_analysis`
(`fotmob_source.py`) now also calls `record_statistical_evidence` on the real FULL_TIME transition -
fires from both `run-scheduled`'s slow cadence and `fpl live-match-poll`'s fast loop, zero new manual step,
zero LLM cost. `run_post_gw_pipeline` also backfills every already-FULL_TIME match on every real run
(`_backfill_statistical_evidence`, itself cheap/idempotent after the first real write) so this closes the
gap for matches that finished before this code existed too, not just future ones.

**Real, serious bug found and fixed live while backfilling GW1, not glossed over.** The first real
production run wrote 1192 rows - roughly 5x too many. Root cause: `detect_match_standouts` originally
matched Understat rows by `season + match_date` ALONE, and real Premier League fixtures routinely share a
calendar date (confirmed live: three genuinely simultaneous 14:00 UTC GW1 kickoffs) - a date-only join
silently pulled every player from every same-day match into each match's own evidence, a real cross-fixture
contamination bug. **Fixed** by intersecting with the match's own real `player_match_state` roster (the
same source the `started` check already reads) before matching Understat rows - re-verified live: 329 real,
correctly-scoped rows (30-37 per match, matching each real match's own real player count), not 1192. A
dedicated regression test (`test_two_real_matches_on_the_same_calendar_date_do_not_contaminate_each_other`)
seeds two real same-day matches with disjoint rosters and proves each match's detection stays scoped to its
own players. The contaminated production rows were deleted and the backfill re-run correctly before any
further verification.

**Real, live-verified result**: real qualitative-implication coverage went from 14 players (100% squad) to
**222 players (208 non-squad)** - confirmed via a direct query, not estimated. Tavernier (the optimizer's
own real #1 transfer target) now has real evidence (GOAL_THREAT: 2 shots/0.48xG; MINUTES: 90 real trusted
minutes) that genuinely did not exist before this pass. Confirmed this new evidence correctly stays inert
for now (`qualitative_adjustment=0.0`, both signals classify as real `NEW_SIGNAL`, sample_size=1) - the
PERSISTENT_TREND gate this project already established for the LLM path applies identically here, so a
single match still never moves a number; the real payoff is that from GW2 onward, EVERY player's second
real match - not just the ~14 someone happened to manually analyze - has a genuine chance to earn a real,
evidence-gated adjustment. Re-ran the real transfer/captain decision after this landed: unchanged
(Tzolis->Tavernier, +12.06, unaffected) - correct and expected, since nothing yet clears the 2-match bar.

**12 new tests** (`tests/test_statistical_evidence.py` - each real threshold firing/not-firing, the
substitute-suppression logic, idempotency, the LLM-row-preservation guarantee, and the cross-fixture
contamination regression). 892/892 full suite. `fpl dashboard` regenerates clean.

**What this does NOT close, stated plainly**: the team-level gap (qualitative tactical reads never
reaching the quantitative Dixon-Coles fit) remains real and unfixed - deliberately scoped out rather than
rushed, since folding a qualitative read into the fit risks the fit's own leakage-safety guarantees
`backtesting/harness.py` depends on, and this pass's time budget didn't support building and proving a
second, safe, additive team-strength supplement to the same standard as everything else here. A real,
disclosed, standard technique exists for a SAFER version of this (comparing a team's real match-level
goals-for/against against its real stored `team_match_state.xg`/`xg_against` - an xG-regression signal,
well short of touching the fit itself) - named as a genuine, scoped follow-up, not silently dropped. The
statistical detector's own confidence is deliberately capped at `medium` (never `high`) - a real threshold
crossing is decent evidence but not equivalent to the nuanced contextual judgment a human/LLM read can add
(e.g. distinguishing a real tactical shift from a one-off).

