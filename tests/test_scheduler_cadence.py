import time

from fpl_agent.scheduler.cadence import recommended_cadence


def _insert_event(conn, event_id, hours_from_now):
    epoch = int(time.time() + hours_from_now * 3600)
    conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,is_current,is_next,"
        "average_entry_score,highest_score,updated_at) VALUES (?,?,?,?,0,0,0,0,NULL,NULL,'t0')",
        (event_id, f"GW{event_id}", "2026-01-01T00:00:00Z", epoch),
    )
    conn.commit()


def test_no_upcoming_deadline_uses_normal_cadence(db_conn):
    cadence = recommended_cadence(db_conn)
    assert cadence.hours_to_deadline is None
    assert cadence.interval_minutes == 360


def test_deadline_day_cadence(db_conn):
    _insert_event(db_conn, 1, hours_from_now=1)
    cadence = recommended_cadence(db_conn)
    assert cadence.interval_minutes == 15


def test_active_window_cadence(db_conn):
    _insert_event(db_conn, 1, hours_from_now=10)
    cadence = recommended_cadence(db_conn)
    assert cadence.interval_minutes == 30


def test_moderate_cadence(db_conn):
    _insert_event(db_conn, 1, hours_from_now=50)
    cadence = recommended_cadence(db_conn)
    assert cadence.interval_minutes == 60


def test_normal_cadence_far_from_deadline(db_conn):
    _insert_event(db_conn, 1, hours_from_now=100)
    cadence = recommended_cadence(db_conn)
    assert cadence.interval_minutes == 360


def test_picks_nearest_upcoming_deadline(db_conn):
    _insert_event(db_conn, 1, hours_from_now=100)
    _insert_event(db_conn, 2, hours_from_now=1)
    cadence = recommended_cadence(db_conn)
    assert cadence.interval_minutes == 15  # the GW2 deadline, not GW1
