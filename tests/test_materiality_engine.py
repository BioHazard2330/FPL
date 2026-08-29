"""Real test for the materiality-engine event routing (2026-08-29, "live
architecture rebuild" pass, milestone 3). Deliberately does NOT re-test
`_maybe_trigger_strategic_plan_recompute`'s own real trigger logic (already
covered by `test_strategic_plan_auto_trigger.py`, and it spawns a real
subprocess when its own preconditions are met - never something to let
run inside a fast unit test) - this proves the EVENT ROUTING itself: which
real bus events reach that function, and which don't, matching
`materiality_engine.py`'s own documented routing table."""
import pytest

import fpl_agent.cli.main as main_mod
from fpl_agent.events.bus import Event, EventBus
from fpl_agent.events.types import EventType
from fpl_agent.live import materiality_engine


@pytest.fixture(autouse=True)
def _isolated_db_path(tmp_path, monkeypatch):
    """`_on_routed_event` opens a real `get_connection()` per event (see
    its own docstring) - redirect it to an isolated temp path so these
    tests never touch the real production `data/fpl.db`, even for a plain
    open/close (the recompute gate itself is stubbed in every test below,
    so nothing ever queries this connection)."""
    monkeypatch.setattr("fpl_agent.database.connection.DATA_DIR", tmp_path)
    monkeypatch.setattr("fpl_agent.database.connection.DB_PATH", tmp_path / "test.db")


def test_routed_event_types_call_the_real_recompute_gate(monkeypatch):
    calls = []
    monkeypatch.setattr(main_mod, "_maybe_trigger_strategic_plan_recompute", lambda conn: calls.append(conn) or "stub reason")

    bus = EventBus()
    materiality_engine.register(bus)
    bus.publish(Event(
        event_type=EventType.AVAILABILITY_CHANGED, entity="player", entity_id=1, occurred_at=Event.now(),
        payload={}, source="test",
    ))
    assert len(calls) == 1


def test_non_routed_event_types_never_call_the_recompute_gate(monkeypatch):
    """Real spec requirement (section 7): a shot/goal/substitution must
    NOT trigger the expensive strategic-plan search directly - only
    through its own downstream AVAILABILITY_CHANGED, never routed here."""
    calls = []
    monkeypatch.setattr(main_mod, "_maybe_trigger_strategic_plan_recompute", lambda conn: calls.append(conn) or "stub reason")

    bus = EventBus()
    materiality_engine.register(bus)
    for event_type in (EventType.GOAL, EventType.ASSIST, EventType.CARD, EventType.SUBSTITUTION, EventType.SHOT):
        bus.publish(Event(event_type=event_type, entity="player", entity_id=1, occurred_at=Event.now(), payload={}, source="test"))
    assert calls == []


def test_every_change_detection_event_type_is_routed():
    """Real coverage check - every real bus EventType `change_detection.py`
    can emit (see its own `_BUS_EVENT_TYPE` map) must be a routed type
    here, or a real price/status/lineup change would silently never
    reach the materiality gate."""
    from fpl_agent.ingestion.change_detection import _BUS_EVENT_TYPE, _DEFAULT_BUS_EVENT_TYPE

    emittable = set(_BUS_EVENT_TYPE.values()) | {_DEFAULT_BUS_EVENT_TYPE}
    assert emittable.issubset(set(materiality_engine._ROUTED_EVENT_TYPES))


def test_a_failing_recompute_check_does_not_break_the_bus(monkeypatch):
    def _raise(conn):
        raise RuntimeError("a real recompute-check bug")

    monkeypatch.setattr(main_mod, "_maybe_trigger_strategic_plan_recompute", _raise)
    bus = EventBus()
    materiality_engine.register(bus)
    bus.publish(Event(  # must not raise
        event_type=EventType.AVAILABILITY_CHANGED, entity="player", entity_id=1, occurred_at=Event.now(),
        payload={}, source="test",
    ))
