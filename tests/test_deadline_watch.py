from datetime import datetime, timezone

from fpl_agent.models import deadline_watch


def test_watch_without_a_deadline_is_quiet(db_conn):
    assert deadline_watch.watch(db_conn, datetime(2026, 11, 27, tzinfo=timezone.utc))["status"] in ("none", "ok")
    assert deadline_watch.raise_alerts(db_conn, datetime(2026, 11, 27, tzinfo=timezone.utc)) == 0
