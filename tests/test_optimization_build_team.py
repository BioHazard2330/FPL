from fpl_agent.database.connection import get_connection
from fpl_agent.database.decisions import log_decision
from fpl_agent.optimization.build_team import (
    LockedDecisionIncomplete,
    LockedSquadConstraints,
    resolve_locked_constraints,
)


def test_no_lock_when_no_build_team_decision_has_ever_been_logged(db_conn):
    assert resolve_locked_constraints(db_conn) is None


def test_no_lock_ignores_decisions_of_a_different_type(db_conn):
    log_decision(
        db_conn, "transfer", "some unrelated decision",
        detail={"must_include_ids": [1], "must_start_ids": [], "exclude_ids": [], "gw_window": 1},
    )

    assert resolve_locked_constraints(db_conn) is None


def test_resolves_the_real_ids_from_the_most_recent_build_team_decision(db_conn):
    log_decision(
        db_conn, "build_team", "first team: A - Best expected value, total_xp=59.38",
        detail={
            "must_include_ids": [542, 427, 368, 426, 557, 411, 165, 8, 418, 109],
            "must_start_ids": [557],
            "exclude_ids": [4],
            "gw_window": 1,
        },
        model_version="calibrated-v2",
    )

    locked = resolve_locked_constraints(db_conn)

    assert locked is not None
    assert locked.must_include_ids == frozenset({542, 427, 368, 426, 557, 411, 165, 8, 418, 109})
    assert locked.must_start_ids == frozenset({557})
    assert locked.exclude_ids == frozenset({4})
    assert locked.gw_window == 1


def test_the_most_recent_of_several_build_team_decisions_wins(db_conn):
    log_decision(
        db_conn, "build_team", "old lock",
        detail={"must_include_ids": [1], "must_start_ids": [], "exclude_ids": [], "gw_window": 1},
    )
    log_decision(
        db_conn, "build_team", "the real, later re-decision",
        detail={"must_include_ids": [2, 3], "must_start_ids": [3], "exclude_ids": [], "gw_window": 1},
    )

    locked = resolve_locked_constraints(db_conn)

    assert locked.must_include_ids == frozenset({2, 3})


def test_a_later_unconstrained_build_team_run_is_a_real_re_decision_not_a_bug(db_conn):
    """This project's own standing convention (already used by
    resolve_tracked_squad_ids): the last real user action is the current
    state. A deliberate unconstrained re-run correctly clears the lock,
    it's not something to guard against."""
    log_decision(
        db_conn, "build_team", "locked",
        detail={"must_include_ids": [1], "must_start_ids": [], "exclude_ids": [], "gw_window": 1},
    )
    log_decision(
        db_conn, "build_team", "unconstrained re-run",
        detail={"must_include_ids": [], "must_start_ids": [], "exclude_ids": [], "gw_window": 1},
    )

    locked = resolve_locked_constraints(db_conn)

    assert locked.must_include_ids == frozenset()
    assert locked.must_start_ids == frozenset()


def test_an_old_style_decision_missing_the_constraint_fields_raises_incomplete(db_conn):
    """Reproduces the exact real shape of decision_id=59/63 in the live DB -
    logged before this persistence fix, only web_names/summary/captain
    stored, no ids at all. Must fail safely (a typed exception the caller
    can catch and log), never guess a squad from web_names alone."""
    log_decision(
        db_conn, "build_team", "first team: A - Best expected value, total_xp=59.38",
        detail={
            "structures": {"A - Best expected value": {"cost": 100.0, "total_xp": 59.38, "squad": ["Haaland"]}},
            "captain": "Haaland", "vice": "B.Fernandes", "risks": [], "narrowly_missed": [], "watchlist": [],
        },
        model_version="calibrated-v2",
    )

    try:
        resolve_locked_constraints(db_conn)
        assert False, "expected LockedDecisionIncomplete"
    except LockedDecisionIncomplete as exc:
        assert "predates constraint persistence" in str(exc)


def test_malformed_constraint_data_raises_incomplete_not_a_crash(db_conn):
    log_decision(
        db_conn, "build_team", "corrupted",
        detail={"must_include_ids": ["not-an-int"], "must_start_ids": [], "exclude_ids": [], "gw_window": 1},
    )

    try:
        resolve_locked_constraints(db_conn)
        assert False, "expected LockedDecisionIncomplete"
    except LockedDecisionIncomplete as exc:
        assert "malformed constraint data" in str(exc)


def test_the_lock_survives_a_fresh_connection_to_the_same_db_file(db_conn, tmp_path, monkeypatch):
    """Real process-restart proof: db_conn is a genuine file-backed sqlite
    DB (see conftest.py), not :memory:. A second, independent connection
    object reading back what the first one committed is the real-world
    equivalent of the scheduler's next 15-minute cycle opening a brand new
    connection after this process has long since exited."""
    log_decision(
        db_conn, "build_team", "locked",
        detail={"must_include_ids": [7, 8, 9], "must_start_ids": [8], "exclude_ids": [], "gw_window": 1},
    )

    fresh_conn = get_connection()
    try:
        locked = resolve_locked_constraints(fresh_conn)
        assert locked is not None
        assert locked.must_include_ids == frozenset({7, 8, 9})
        assert locked.must_start_ids == frozenset({8})
    finally:
        fresh_conn.close()
