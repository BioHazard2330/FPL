from fpl_agent.alerts.engine import Notifier, deliver_pending_alerts, pending_alerts


class RecordingNotifier(Notifier):
    def __init__(self):
        self.sent = []

    def send(self, alert):
        self.sent.append(alert)


def _insert_event(conn, severity, event_id=None):
    conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, "
        "sources, confidence, severity, fpl_impact, action_required) "
        "VALUES ('status_change','player',1,'a','i','t0','[\"fpl_api\"]','CONFIRMED',?,NULL,0)",
        (severity,),
    )
    conn.commit()


def test_only_high_and_critical_are_pending(db_conn):
    _insert_event(db_conn, "LOW")
    _insert_event(db_conn, "MEDIUM")
    _insert_event(db_conn, "HIGH")
    _insert_event(db_conn, "CRITICAL")

    pending = pending_alerts(db_conn)
    assert {a.severity for a in pending} == {"HIGH", "CRITICAL"}
    assert len(pending) == 2


def test_delivered_alerts_are_not_redelivered(db_conn):
    _insert_event(db_conn, "HIGH")

    notifier = RecordingNotifier()
    first = deliver_pending_alerts(db_conn, notifier)
    assert len(first) == 1
    assert len(notifier.sent) == 1

    second = deliver_pending_alerts(db_conn, notifier)
    assert second == []
    assert len(notifier.sent) == 1  # not called again

    assert pending_alerts(db_conn) == []
