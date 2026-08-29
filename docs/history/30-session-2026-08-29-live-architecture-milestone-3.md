# Session 2026-08-29: live architecture rebuild, milestone 3 (materiality engine)

Continuation of the "live architecture rebuild" spec (milestone 1: event
bus + fast engine; milestone 2: SSE transport). User said "continue" after
milestone 2's report offered the materiality-gate wiring as the next
candidate.

## Real gap closed

`cli/main.py::_maybe_trigger_strategic_plan_recompute` was already real,
already tested (`test_strategic_plan_auto_trigger.py`) - a genuine HIGH-
severity `change_events` check, a real squad-mismatch check, a real
stale-decision check, a real self-healing overlap lock. But it was only
ever CHECKED once per `run_scheduled` tick (15min-6h cadence, deadline/
live-window adaptive) - a real squad player becoming injured seconds
after a tick just ran waits for the NEXT tick before the check even runs.

## New: `live/materiality_engine.py`

Subscribes to the milestone-1 event bus for `AVAILABILITY_CHANGED`,
`PLAYER_STATE_CHANGED`, `LINEUP_CONFIRMED`, `PRICE_CHANGED`,
`FIXTURE_CHANGED` - exactly the real event types `change_detection.py`'s
own `record_event` (wired onto the bus in milestone 1) can emit. On any
of these, calls the existing `_maybe_trigger_strategic_plan_recompute`
directly - unchanged, unaltered, still the single source of truth for
"is this actually material". Deliberately does NOT route GOAL/ASSIST/
CARD/SUBSTITUTION/SHOT here, per the spec's own routing table (section 7):
those are FAST-ENGINE concerns (`live/fast_engine.py`, milestone 1) - a
shot or a substitution alone is never worth a real 2-10 minute beam
search; only a resulting real AVAILABILITY_CHANGED (an injury) would be,
and that already flows through the routed path.

Each real trigger check opens its own short-lived connection
(`get_connection()`) rather than sharing the connection object of whatever
process produced the original event - deliberate, since the check doesn't
need to share state with the producer, and connections are thread-affine
(the same lesson milestone 2's SSE server learned the hard way).

## Wiring

Registered at the three real event-producing entry points: `run_scheduled`
(before `run_sync()` - that's where the real FPL-side price/status/lineup
change_detection calls actually happen), `live_match_poll_cmd`, and
`refresh_in_progress_matches` (both call `sync_match` directly, matching
the same pattern `live/fast_engine.py`'s registration already uses).

## Tests

4 new tests (`test_materiality_engine.py`):
- routed event types call the real gate (verified via a monkeypatched
  stub, never letting the real function - which spawns a real subprocess
  when its own preconditions are met - actually run inside a unit test).
- non-routed event types (GOAL/ASSIST/CARD/SUBSTITUTION/SHOT) never call
  it - the real spec-7 requirement, made explicit.
- every real bus `EventType` `change_detection.py` can emit is provably a
  routed type here (a coverage check against that module's own
  `_BUS_EVENT_TYPE` map, not a hand-maintained duplicate list that could
  silently drift out of sync).
- a raising recompute check never breaks the bus (same handler-isolation
  guarantee `test_event_bus.py` already covers generically, reconfirmed
  for this specific real handler).

Full suite green (count recorded in `PROJECT_STATE.md`'s own entry for
this milestone). No real `fpl strategic-plan` subprocess was spawned
during testing - deliberately avoided given the real cost (~2-10 minutes)
of that search; `_maybe_trigger_strategic_plan_recompute`'s own internal
trigger logic is separately, already covered by
`test_strategic_plan_auto_trigger.py`.

## Genuinely not done this milestone (real, disclosed)

FPL-side provider abstraction (a formal `FootballDataProvider`/
`FplProvider` interface) - still unbuilt. `match_event`/`change_event`
SSE channels still aren't rendered browser-side (milestone 2's disclosed
gap). Decision hysteresis (a minimum-EV-advantage/confidence-persistence
requirement before REPLACING an already-current recommendation) is a
real, distinct ask from materiality (which only asks "is a recompute
worth running", not "should the NEW result actually replace the old
recommendation") - not touched this pass. Real production verification
against a genuinely reactive trigger during a live match was not possible
(no GW was live this session).
