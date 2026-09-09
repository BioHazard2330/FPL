"""Real regression coverage for the season clock's backend half
(2026-09-09). This block runs inside the real live-match poll cycle, so the
tests that matter most are the ones proving it cannot take that cycle down."""
from fpl_agent.monitoring.live_snapshot import _deadline_block


def _event(conn, event, deadline, finished=0):
    conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, updated_at) VALUES (?,?,?,?,?,0,0,0,?)",
        (event, f"Gameweek {event}", deadline, 1789038000 + event * 604800, finished, "t0"),
    )


def test_deadline_block_reports_the_next_unfinished_deadline(db_conn):
    _event(db_conn, 3, "2020-09-04T17:30:00Z", finished=1)
    _event(db_conn, 4, "2099-09-12T12:30:00Z")
    _event(db_conn, 5, "2099-09-18T17:30:00Z")
    db_conn.commit()

    out = _deadline_block(db_conn)
    assert out["next_deadline_event"] == 4
    assert out["next_deadline_time"] == "2099-09-12T12:30:00Z"
    assert out["next_deadline_name"] == "Gameweek 4"
    # the deadline just gone, for a UI that needs to know how long ago the
    # gameweek locked
    assert out["last_deadline_time"] == "2020-09-04T17:30:00Z"


def test_deadline_block_passes_the_timestamp_through_verbatim(db_conn):
    """No countdown is computed server-side on purpose - a countdown is stale
    the instant it is serialized, so the browser ticks the real timestamp."""
    _event(db_conn, 4, "2099-09-12T12:30:00Z")
    db_conn.commit()
    assert _deadline_block(db_conn)["next_deadline_time"] == "2099-09-12T12:30:00Z"


def test_deadline_block_is_empty_when_no_future_deadline_exists(db_conn):
    """End of season: honestly empty, never a fabricated next deadline."""
    _event(db_conn, 38, "2020-05-24T15:00:00Z", finished=1)
    db_conn.commit()
    out = _deadline_block(db_conn)
    assert out["next_deadline_event"] is None
    assert out["next_deadline_time"] is None


def test_deadline_block_never_raises_into_the_live_poll(db_conn):
    """The single most important property here. This runs inside the real
    live-match poll; a clock is never worth risking that cycle for, so any
    failure degrades to an empty block and the UI simply shows no countdown."""
    class Exploding:
        def execute(self, *_a, **_k):
            raise RuntimeError("simulated DB failure")

    assert _deadline_block(Exploding()) == {}
