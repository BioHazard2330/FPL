# Plan 1b design — scenario engine, chip DP scheduling, risk output

Brainstormed 2026-08-16. Builds on the Pillar 1 section of
`docs/superpowers/specs/2026-08-15-market-rivaling-architecture-design.md`, which already pins
down function signatures, table shapes, and the CLI surface. This doc covers what that spec left
as brainstorm-time judgment calls: scope decomposition, the chip-DP hit-week mechanism, the
scenario-reuse/runtime strategy, and testing lessons carried forward from Plan 1a's final review.

## Scope

Plan 1b = scenario engine + chip DP scheduler + `fpl season-sim` CLI + heuristic backtest
extension. Sampled effective ownership, originally part of a combined Plan 1b, is split out to
its own **Plan 1c** (own future brainstorm cycle) — it's functionally independent, nothing in
this plan's cluster consumes EO. See the architecture spec's updated Pillar 1 section for the
full split rationale.

## Migration note

No new migration for this plan. Scenario engine is pure computation over existing Dixon-Coles
fixture/team-strength data; chip DP reads the existing `chip_windows` table; `season-sim` logs to
the existing `decisions` table, whose evidence JSON already supports arbitrary structured output
(confirmed against the actual Phase 8 schema, not assumed). Migration `0011`, originally reserved
for this plan under the old combined grouping, now belongs to Plan 1c's EO table instead.

## Components

- **`models/scenario_engine.py`** (new) —
  `sample_season_scenarios(conn, squad_ids, from_event, horizon_gw, n_trials=1000, rng=None) ->
  list[ScenarioOutcome]`. Draws real scorelines from Dixon-Coles Poisson distributions (not point
  estimates), propagates through the existing `calibrated-v2` building blocks, respects
  blank/double-GW structure as already surfaced by `fixture-watch`. Vectorized with numpy — batch
  the Poisson draws across trials, not a per-trial Python loop — to meet the runtime target below.
  `rng` is an explicit parameter (not module-global state) specifically so tests can pin a seed
  for reproducible-distribution assertions.

- **`optimization/chips.py`** (extended) —
  `schedule_chips(conn, squad_trajectory, chip_windows, scenario_draw) -> ChipSchedule`. DP over
  chip-window-eligible GWs, state = (chip-availability flags, GW index), marginal value from
  `scenario_draw`'s trial outcomes. `scenario_draw` is a single shared sample produced once per
  `schedule_chips` call (see Scenario reuse below) — both the baseline trajectory and any
  advisory hit-candidate are scored against the *same* draw. Existing single-decision-point
  functions (`bench_boost_value`/`triple_captain_value`/`wildcard_value`/`freehit_value`) are
  untouched — `schedule_chips` is additive.

- **`fpl season-sim --squad <path> [--trials N]`** (new CLI) — runs `sample_season_scenarios`
  over the rest of the season, reports P10/P50/P90 via `numpy.percentile`, plus `schedule_chips`'s
  recommended timing including any advisory hit-week deviations. Logs to `decisions`.

- **`backtesting/harness.py`** (extended) — scores differential/trap/template flags against
  Pillar 0's historical corpus. Note: these flags currently run on raw `selected_by_percent`
  (sampled EO doesn't exist until Plan 1c) — this piece backtests what's available now; revisit
  once Plan 1c ships if the backtest should be re-run against sampled EO instead.

## Chip DP hit-week mechanism

**Problem:** Plan 1a's beam search can only make one transfer per GW step, and free-transfer
accrual means a hit (`is_hit=True`) is realistically only reachable at horizon step 0. If
`schedule_chips` just trusts the beam search's `TransferSequence` as ground truth, it inherits
that blind spot — it can't recognize "a hit two GWs from now would unlock a much better bench
boost window" if the trajectory it's given never considered that hit.

**Decision: advisory-only, reusing the existing single-swap evaluator (not a new search
algorithm).** For each chip-window-eligible GW, `schedule_chips` calls the existing
`evaluate_transfer`/`best_transfer_for_player` (Plan 1a's single-swap functions) to generate
hit-transfer candidates local to that GW, scored against `scenario_draw`'s sampled distributions
instead of point-estimate EV. This is independent of whatever the beam search's trajectory
decided at that GW — the DP can surface a recommendation that diverges from the baseline
trajectory ("beam search says roll at GW14, but a hit there unlocks +X EV at P50 by enabling
better BB timing"). It never splices into or mutates the `TransferSequence` itself — divergent
recommendations are reported as a distinct, clearly-labeled field on `ChipSchedule`, not merged
into the baseline squad plan.

Two other approaches were considered and rejected for this plan's scope:
- A local mini-beam re-search per chip window (short-horizon beam search seeded from the
  trajectory's squad state, allowing hit candidates) would catch 2-transfer combos near a window
  that the single-swap approach can't, but introduces a second search algorithm alongside Plan
  1a's beam search — real added surface area. Worth revisiting later if the advisory-only
  approach proves too coarse against real data, but not in scope now.
- A fully joint transfer+chip+hit DP across the whole horizon would be the most correct, but
  effectively redesigns Plan 1a's beam search — too large for this plan, would need its own
  plan if ever pursued.

**Layering rule (carried from Plan 1a):** baseline-trajectory EV and advisory-hit EV are reported
as separate fields, never conflated into one number — the same FACTS/DERIVED/REASONING
separation that Plan 1a's final review enforced for `total_net_ev` vs `tiebreak_adjustment`.

## Scenario reuse and runtime budget

**Target:** `fpl season-sim` and chip DP evaluation should run in seconds to low tens of seconds,
not minutes — normal CLI-command latency, not a background job.

**Decision: one shared scenario draw per `schedule_chips` (or `season-sim`) call, reused across
every chip-window and hit-candidate evaluation within that call**, rather than an independent
redraw per candidate. Scoreline sampling happens once; only the squad-scoring step varies per
candidate. This is also the statistically correct choice for *ranking* candidates against each
other fairly — comparing candidates against a shared underlying draw is a correlated comparison,
which is what you want when the question is "which of these is better," not independent
uncertainty estimates for each one in isolation. An independent-redraw-per-candidate variant was
considered and rejected: statistically purer in isolation, but multiplies sampling cost by the
number of candidates evaluated and would likely blow the runtime target.

## Data flow

Beam search trajectory (Plan 1a) → `schedule_chips` treats as baseline → scenario engine draws
shared scorelines once → chip DP scores the baseline trajectory per window against the draw →
advisory hit-candidates (single-swap evaluator) scored against the same draw → `ChipSchedule`
carries both the DP-optimal timing over the baseline *and* any flagged divergent-hit
recommendations, kept in clearly separate fields.

## Error handling

- Missing/incomplete fixture data for blank GWs: defer to existing `fixture-watch` blank/DGW
  detection rather than reimplementing detection logic here.
- A chip already used this season: excluded from the DP state space outright, not silently
  skipped as if still available.
- `season-sim` horizon exceeding available `chip_windows` data: explicit bounded warning in
  output, not silent truncation.

## Testing

Standard TDD/SDD cadence per task (failing test → verify fail → implement → verify pass → full
suite → commit), same bar as every prior phase/pillar. Two lessons carried forward from Plan 1a's
whole-branch final review, which caught real gaps that per-task review structurally couldn't:

1. **Scenario engine tests must pin an `rng` seed and assert distributional properties**
   (percentile ranges, not exact values), and must include at least one test across a real
   multi-GW horizon — not everything pinned to a single GW/event the way Plan 1a's mutation
   testing caught horizon-awareness going untested because every fixture pinned `event=1`.
2. **Chip DP tests must include a fixture where the advisory hit-recommendation actually
   diverges from the baseline trajectory** — proving the "richer than trusting the fixed hit
   placement" capability is genuinely reachable by some test, not just written but never
   exercised by any fixture in the suite.

Plus one new integration test extending `test_e2e_pillar0_lifecycle.py`'s pattern to prove this
plan's pieces compose (scenario engine → chip DP → `season-sim` → decision journal). Live
verification at the end of the plan against the real player pool, same bar Phase 9, Pillar 0, and
Plan 1a all used before being marked done.
