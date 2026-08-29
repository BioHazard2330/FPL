"""Real in-process event bus (2026-08-29, "live architecture rebuild" pass,
milestone 1 - direct spec: "every downstream component subscribes to these
events"). This project runs as a single Python process per invocation
(`fpl live-match-poll`/`fpl run-scheduled`, Windows Task Scheduler) - a
synchronous, in-memory publish/subscribe dispatcher is the real, correct
scope here, not a distributed message broker (Kafka/RabbitMQ/Redis would
be real infrastructure this project's own "free resources only, no paid
services" rule and its single-laptop deployment don't call for or support).

Handlers run synchronously, in subscription order, on the publishing
thread - a handler that raises is logged and skipped, never allowed to
break the publisher or a later handler (the same "one degraded source must
never break an otherwise-healthy pass" posture this project already uses
throughout `run_scheduled`/`live_match_poll_cmd`)."""
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from fpl_agent.events.types import EventType

_logger = logging.getLogger("fpl_agent.events")


@dataclass(frozen=True)
class Event:
    """A real, structured occurrence - never free-text. `entity`/
    `entity_id` name the real thing this event is about (e.g.
    entity="player", entity_id=737066); `payload` carries the real
    type-specific detail (minute, score, old/new value, ...) - a plain
    dict, not a fixed schema, since each `EventType` carries different
    real fields (documented in the producer that emits it, not here)."""
    event_type: EventType
    entity: str
    entity_id: int | str | None
    occurred_at: str
    payload: dict = field(default_factory=dict)
    source: str = "unknown"

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()


Handler = Callable[[Event], None]


class EventBus:
    """One bus per process (see the module-level `bus` singleton below) -
    every real producer (`sync_match`, `change_detection`, future FPL-side
    producers) publishes here; every real consumer (`live/fast_engine.py`,
    a future materiality engine, a future SSE transport) subscribes here.
    No consumer re-queries the database to find "what just happened" - it
    receives the real event directly."""

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[Handler]] = defaultdict(list)
        self._wildcard_handlers: list[Handler] = []
        self.published: list[Event] = []  # real, bounded audit trail - see _MAX_HISTORY
        self._max_history = 500

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: Handler) -> None:
        """A wildcard subscriber (every event, any type) - real use case:
        a reconciliation/audit log, or (future milestone) the SSE
        transport that forwards every real event to connected browsers."""
        self._wildcard_handlers.append(handler)

    def publish(self, event: Event) -> None:
        self.published.append(event)
        if len(self.published) > self._max_history:
            del self.published[: len(self.published) - self._max_history]
        for handler in list(self._handlers.get(event.event_type, ())) + list(self._wildcard_handlers):
            try:
                handler(event)
            except Exception:
                _logger.exception(
                    "event handler failed for %s (entity=%s id=%s) - continuing, other subscribers unaffected",
                    event.event_type, event.entity, event.entity_id,
                )

    def reset(self) -> None:
        """Test-only: clear all subscriptions and history so tests don't
        leak state into each other via the module-level singleton."""
        self._handlers.clear()
        self._wildcard_handlers.clear()
        self.published.clear()


bus = EventBus()
