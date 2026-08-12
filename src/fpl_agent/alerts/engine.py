"""
Alert engine (section 84-86). Only HIGH/CRITICAL severity change_events become
alerts - matches "don't notify me about every piece of football news." Delivery
is tracked via change_events.alerted_at so a re-run doesn't re-alert the same event.
"""

import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

_ALERT_SEVERITIES = ("CRITICAL", "HIGH")


@dataclass(frozen=True)
class Alert:
    change_event_id: int
    event_type: str
    entity: str
    entity_id: int
    severity: str
    old_value: str | None
    new_value: str | None
    detected_at: str


class Notifier(ABC):
    @abstractmethod
    def send(self, alert: Alert) -> None: ...


class TerminalNotifier(Notifier):
    """Only channel enabled - user chose terminal-only notifications (section 84)."""

    def send(self, alert: Alert) -> None:
        print(
            f"[{alert.severity}] {alert.event_type} {alert.entity}#{alert.entity_id}: "
            f"{alert.old_value} -> {alert.new_value}  ({alert.detected_at})"
        )


def pending_alerts(conn: sqlite3.Connection) -> list[Alert]:
    placeholders = ",".join("?" * len(_ALERT_SEVERITIES))
    rows = conn.execute(
        f"SELECT id, event_type, entity, entity_id, severity, old_value, new_value, detected_at "
        f"FROM change_events WHERE alerted_at IS NULL AND severity IN ({placeholders}) "
        f"ORDER BY detected_at",
        _ALERT_SEVERITIES,
    ).fetchall()
    return [
        Alert(
            change_event_id=r["id"], event_type=r["event_type"], entity=r["entity"],
            entity_id=r["entity_id"], severity=r["severity"],
            old_value=r["old_value"], new_value=r["new_value"], detected_at=r["detected_at"],
        )
        for r in rows
    ]


def mark_alerted(conn: sqlite3.Connection, change_event_ids: list[int]) -> None:
    if not change_event_ids:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "UPDATE change_events SET alerted_at=? WHERE id=?",
        [(now, cid) for cid in change_event_ids],
    )
    conn.commit()


def deliver_pending_alerts(conn: sqlite3.Connection, notifier: Notifier) -> list[Alert]:
    alerts = pending_alerts(conn)
    for alert in alerts:
        notifier.send(alert)
    mark_alerted(conn, [a.change_event_id for a in alerts])
    return alerts
