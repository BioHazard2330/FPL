# Session 2026-08-29: live architecture rebuild, milestone 1 (event bus + fast engine)

Direct user spec ("LIVE ARCHITECTURE REBUILD — DATA FIRST, ZERO UI
REDESIGN"): a real football event must automatically propagate through
FOOTBALL PROVIDER -> INGESTION -> CANONICAL LIVE STATE -> ... -> DECISION
-> DASHBOARD, no widget-specific fetches, no second parallel data model.
Explicitly no UI/CSS changes this pass.

Two clarifications resolved before starting (AskUserQuestion): (1) the
spec's "legitimate/authorized provider" language conflicts with this
project's own standing "free resources only, no paid APIs" rule - user
chose to keep FotMob as the real provider implementation, wrapped behind
a real interface, rather than pursue a paid contract. (2) this is a real
multi-session rebuild - user chose incremental milestones with a report
at each real one, not an all-at-once attempt.

## Milestone 1 scope

The foundation everything else depends on: a real typed event bus +
FotMob-side event production (match lifecycle + goals/assists/cards/subs)
+ a FAST ENGINE consuming it. SSE/WebSocket transport, FPL-side provider
abstraction, materiality-engine consolidation, decision hysteresis, and
the reconciliation loop are explicitly NOT in this milestone - later ones,
in dependency order.

## New: `events/` package

`EventType` (str enum) - the real vocabulary from the spec: MATCH_STARTED/
HALFTIME/RESUMED/FINISHED, GOAL, ASSIST, SHOT, CARD, SUBSTITUTION,
LINEUP_CONFIRMED, PLAYER_STATE_CHANGED, TEAM_STATE_CHANGED,
FPL_POINTS_CHANGED, BONUS_CHANGED, PRICE_CHANGED, AVAILABILITY_CHANGED,
FIXTURE_CHANGED. `BIG_CHANCE` is defined but never emitted - checked
FotMob's real shotmap payload directly, it carries no per-shot big-chance
flag (only an aggregate team-level count), so no per-shot heuristic was
invented for it.

`EventBus` - a real, synchronous, in-process publish/subscribe dispatcher.
This project runs as a single Python process per invocation (Windows Task
Scheduler triggers `fpl live-match-poll`/`fpl run-scheduled`) - a real
message broker (Kafka/Redis) would be real infrastructure this project's
own free-resources rule and single-laptop deployment don't call for. A
handler that raises is logged and skipped, never allowed to break the
publisher or a later subscriber (unit-tested directly,
`test_event_bus.py`).

## New: `live/fast_engine.py` + migration 0036 (`live_player_state`)

Real gap closed: a SUBSTITUTION event (a player coming OFF) was written
to `player_match_state.substituted_off_minute` and then never read by
anything downstream - no engine ever concluded "this player's real
minutes this match are now final." `live_player_state` is that real,
versioned, canonical fact (`minutes_locked`, `minutes_at_lock`,
`last_event_type`, `state_version`) - a real fast-engine subscriber
locks it on SUBSTITUTION (the real OUT player specifically) and on
MATCH_FINISHED (every real player who featured, not just squad-tracked
ones - this table is genuinely about "what's true", not scoped to one
squad). Deliberately does NOT feed this into `models/expected_minutes.py`
or any projection/optimizer math this pass - the user's own standing
instruction ("do not touch optimizer mathematics unless a concrete bug
forces it") - this is the FAST ENGINE's own derived state, a real next-
milestone item to wire into projections.

## `fotmob_source.py::sync_match` - real event production

Added a real "is this a genuinely NEW incident this tick" check before
publishing anything - reuses `match_events`'s own real
`UNIQUE(match_id, source, source_event_id)` constraint (already committed
to in migration 0025) as the identity key, so a re-sync of an
already-known goal/card/substitution never refires it. For each real new
incident: Goal -> `EventType.GOAL` (and a real `EventType.ASSIST` when
FotMob's own `assistPlayerId` field is present - confirmed live against
the actual payload), Card -> `EventType.CARD`, Substitution ->
`EventType.SUBSTITUTION` with both the real IN and OUT player resolved via
the existing `player_match_state` fotmob-id crosswalk (no second name-
matching pass). `models/match_intelligence.py::MatchEvent` gained a real
`extra: dict` field carrying this OUT-player/assist detail that the
persisted `match_events` row doesn't need but a live bus subscriber does.

Real match-lifecycle transitions (MATCH_STARTED/HALFTIME/RESUMED/
FINISHED) are detected by comparing `prior_status` to the newly-parsed
`match.status`, generalizing the FULL_TIME-only check
`maybe_enqueue_analysis` already made (that call is unchanged - this is
an additional, real dispatch onto the event bus for any live subscriber).

**Real bug found + fixed while writing this milestone's own deterministic
test**: the transition check required `prior_status is not None`, so a
fixture's very first real sync (`prior_status_row` is `None` the first
time `sync_match` has ever seen it) never fired `MATCH_STARTED` at all -
and a fixture's first real poll is very often already LIVE (a scheduled
poll landing after kickoff), not PRE_MATCH. Fixed: a `None` prior status
is now treated as the real equivalent of PRE_MATCH for transition-
detection purposes.

## `change_detection.py::record_event` - unified onto the same bus

Price/status/lineup-confirmed/kickoff-reminder changes now ALSO publish
onto the same process-wide bus (`PRICE_CHANGED`/`AVAILABILITY_CHANGED`/
`LINEUP_CONFIRMED`/`FIXTURE_CHANGED`; the remaining event_type strings -
new_player/club_change/setpiece_change/predicted_lineup_change/
start_percent_change - all genuinely are "something about this player's
state changed" and map to the generic `PLAYER_STATE_CHANGED` rather than
inventing a bus type per DB event_type). The real, persisted
`change_events` INSERT is completely unchanged - this is a real,
additional dispatch, not a replacement. New regression test confirms a
real status change reaches a real subscribed handler.

## Deterministic E2E test (spec section 14)

`test_events_pipeline.py` feeds a real, mock-shaped 3-tick FotMob payload
sequence through the ACTUAL `sync_match` production code path (not a
fake/simplified path):

1. LIVE + a real goal+assist -> asserts `MATCH_STARTED`/`GOAL`/`ASSIST`
   fire exactly once, with the real internal player ids resolved
   correctly; re-syncing the identical tick does NOT refire either.
2. LIVE + a real substitution -> asserts `SUBSTITUTION` fires with the
   real IN/OUT player ids, and `live_player_state` locks the OUT player's
   minutes (the ON player stays unlocked).
3. FULL_TIME -> asserts `MATCH_FINISHED` fires and every real player who
   featured now has locked minutes, with the OUT player's `state_version`
   having incremented across both real updates (substitution lock, then
   full-time lock) - a real, versioned fact, never silently overwritten.

## Tests

1267 tests pass (full suite; 7 new this session: 6 in `test_event_bus.py`,
1 in `test_change_detection.py`, plus the pipeline test file itself and
its assertions). No UI/CSS files touched this pass, per the spec's own
"zero UI redesign" instruction.

## Genuinely not done this milestone (real, disclosed)

SSE/WebSocket transport (the browser still polls `live_snapshot.json` on
its existing ~10s cadence - a real, separate later milestone, since it
needs an actual persistent server process this project doesn't run yet).
FPL-side provider abstraction (a formal `FootballDataProvider`/`FplProvider`
interface wrapping the existing FotMob/FPL-API ingestion modules - the
event-production wiring this pass did is provider-agnostic in spirit but
not yet behind a named interface). Materiality-engine consolidation
(fast-vs-deep routing already exists in spirit - `live_snapshot.py` cheap
vs `_maybe_trigger_strategic_plan_recompute` gated - but isn't wired
through the new bus yet). Decision hysteresis, the periodic reconciliation
loop, and end-to-end latency instrumentation are all real, scoped, later
work. Real production verification against a genuinely live match was not
possible this session - none was live while this was built (matches were
starting "this evening" per the user's own note) - everything here is
verified via the deterministic mock-payload test instead, honestly
disclosed as such.
