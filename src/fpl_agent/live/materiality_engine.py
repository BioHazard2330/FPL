"""Real MATERIALITY ENGINE (2026-08-29, "live architecture rebuild" pass,
milestone 3 - direct spec sections 6/7: "do not run the expensive
optimizer for every minor event... injury/availability changes -> full
decision engine update"). Makes the ALREADY-REAL, already-tested
materiality gate (`cli/main.py::_maybe_trigger_strategic_plan_recompute`,
built 2026-08-29 in an earlier session - real HIGH-severity `change_events`
check, real squad-mismatch check, real stale-decision check, a real
self-healing overlap lock) reactive: fires the instant a real subscribed
event lands on the bus, rather than only being checked once per
`run_scheduled` tick (today's real latency floor is however long until
the NEXT scheduled cycle happens to run).

Deliberately does NOT re-implement or alter what counts as material -
that logic stays exactly where it is and exactly as tested
(`_maybe_trigger_strategic_plan_recompute`/`models/decision_freshness.
has_material_change_since`), per the standing "do not touch the optimizer
mathematics" constraint. This module is pure routing: which real bus
events are even worth checking against that gate, and running the check
itself in a fresh, short-lived connection (never sharing the connection
object across threads/processes - the same thread-affinity lesson
milestone 2 already learned the hard way).

Real routing table (spec section 7's own examples, applied to this
project's real event vocabulary):
- AVAILABILITY_CHANGED, PLAYER_STATE_CHANGED (club_change/new_player/
  setpiece_change/predicted_lineup_change/start_percent_change),
  LINEUP_CONFIRMED, PRICE_CHANGED, FIXTURE_CHANGED - these are exactly the
  real `change_events` rows `has_material_change_since` already scans, so
  each is a real candidate trigger (the existing severity/squad-membership
  gate inside that function decides whether THIS specific one clears the
  bar, same as it always has).
- GOAL, ASSIST, CARD, SUBSTITUTION, SHOT - real match events, but NOT
  routed here. Per spec's own table, these are FAST-ENGINE concerns (live
  points/projection bookkeeping - `live/fast_engine.py`), not "recompute
  the 8-GW strategic plan" material. A red card or a substitution can
  become material only through its downstream AVAILABILITY_CHANGED (e.g.
  a resulting injury) - never routed here directly, to avoid firing an
  expensive real beam search on every single in-play kick of the ball."""
import logging

from fpl_agent.events.bus import Event, EventBus
from fpl_agent.events.types import EventType

_logger = logging.getLogger("fpl_agent.materiality_engine")

_ROUTED_EVENT_TYPES = (
    EventType.AVAILABILITY_CHANGED,
    EventType.PLAYER_STATE_CHANGED,
    EventType.LINEUP_CONFIRMED,
    EventType.PRICE_CHANGED,
    EventType.FIXTURE_CHANGED,
)


def _on_routed_event(event: Event) -> None:
    from fpl_agent.cli.main import _maybe_trigger_strategic_plan_recompute
    from fpl_agent.database.connection import get_connection

    conn = get_connection()
    try:
        reason = _maybe_trigger_strategic_plan_recompute(conn)
        if reason is not None:
            _logger.info(
                "materiality engine: %s (%s) triggered a real strategic-plan recompute - %s",
                event.event_type.value, event.entity_id, reason,
            )
    except Exception:
        _logger.exception(
            "materiality engine: recompute check failed for a real %s event - continuing, "
            "the next real routed event (or the next run_scheduled tick) will retry",
            event.event_type.value,
        )
    finally:
        conn.close()


def register(event_bus: EventBus) -> None:
    """Real, idempotent-in-spirit registration - call once per real process
    at any entry point that produces the events above (`run_scheduled`,
    `live_match_poll_cmd`, `refresh_in_progress_matches`). Deliberately
    takes no `conn` (unlike `live/fast_engine.py::register`) - each real
    trigger check opens its OWN short-lived connection (see `_on_routed_
    event`'s own docstring reasoning), since the check itself doesn't need
    to share state with whatever connection originally produced the
    event."""
    for event_type in _ROUTED_EVENT_TYPES:
        event_bus.subscribe(event_type, _on_routed_event)
