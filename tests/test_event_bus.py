"""Unit tests for the real in-process event bus (2026-08-29, "live
architecture rebuild" pass, milestone 1). Separate from
`test_events_pipeline.py`'s end-to-end integration test - this covers the
bus's own real mechanics in isolation (subscription, wildcard dispatch,
handler-exception isolation, bounded history)."""
from fpl_agent.events.bus import Event, EventBus
from fpl_agent.events.types import EventType


def _event(event_type=EventType.GOAL, entity_id=1):
    return Event(event_type=event_type, entity="player", entity_id=entity_id, occurred_at=Event.now())


def test_subscribe_and_publish_reaches_the_real_handler():
    bus = EventBus()
    received = []
    bus.subscribe(EventType.GOAL, received.append)
    bus.publish(_event(EventType.GOAL))
    assert len(received) == 1
    assert received[0].event_type == EventType.GOAL


def test_handler_only_receives_its_own_subscribed_type():
    bus = EventBus()
    goal_received, card_received = [], []
    bus.subscribe(EventType.GOAL, goal_received.append)
    bus.subscribe(EventType.CARD, card_received.append)
    bus.publish(_event(EventType.GOAL))
    assert len(goal_received) == 1
    assert len(card_received) == 0


def test_wildcard_subscriber_receives_every_real_event_type():
    bus = EventBus()
    received = []
    bus.subscribe_all(received.append)
    bus.publish(_event(EventType.GOAL))
    bus.publish(_event(EventType.SUBSTITUTION))
    assert len(received) == 2


def test_a_raising_handler_never_blocks_other_real_subscribers():
    """Real requirement (spec: "one degraded source must never break an
    otherwise-healthy pass") - a broken handler must not stop the bus
    dispatching to the next one, nor propagate out of `publish`."""
    bus = EventBus()
    received = []

    def broken_handler(event):
        raise RuntimeError("a real handler bug")

    bus.subscribe(EventType.GOAL, broken_handler)
    bus.subscribe(EventType.GOAL, received.append)
    bus.publish(_event(EventType.GOAL))  # must not raise
    assert len(received) == 1


def test_published_history_is_bounded_and_reset_clears_it():
    bus = EventBus()
    bus._max_history = 3
    for i in range(5):
        bus.publish(_event(EventType.GOAL, entity_id=i))
    assert len(bus.published) == 3
    assert [e.entity_id for e in bus.published] == [2, 3, 4]  # oldest trimmed, real order preserved
    bus.reset()
    assert bus.published == []


def test_reset_clears_subscriptions_too():
    bus = EventBus()
    received = []
    bus.subscribe(EventType.GOAL, received.append)
    bus.reset()
    bus.publish(_event(EventType.GOAL))
    assert received == []
