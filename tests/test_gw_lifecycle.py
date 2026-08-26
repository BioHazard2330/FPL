from datetime import datetime, timedelta, timezone

from fpl_agent.models.gw_lifecycle import compute_gw_lifecycle_state, needs_post_gw_pipeline

_PAST = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
_FUTURE = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")


def _seed_teams(conn):
    for i in (1, 2, 3, 4):
        conn.execute(
            "INSERT INTO teams (id, code, name, short_name, strength_overall_home, strength_overall_away, "
            "strength_attack_home, strength_attack_away, strength_defence_home, strength_defence_away, pulse_id, updated_at) "
            "VALUES (?,?,?,?,3,3,0,0,0,0,?,'t0')",
            (i, i, f"Team{i}", f"T{i}", i),
        )
    conn.commit()


def _seed_event(conn, event, deadline, is_current=1):
    conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (?,?,?,1,0,0,?,0,'t0')",
        (event, f"GW{event}", deadline, is_current),
    )
    conn.commit()


def _seed_fixture(conn, fid, event, team_h, team_a, started, finished):
    conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,'t0')",
        (fid, fid, event, "2026-08-21T19:00:00Z", team_h, team_a, finished, started),
    )
    conn.commit()


def _seed_healthy_fixtures_source(conn, failure_count=0):
    conn.execute(
        "INSERT INTO source_health (source_name, failure_count) VALUES ('fpl_api_fixtures', ?) "
        "ON CONFLICT(source_name) DO UPDATE SET failure_count=excluded.failure_count",
        (failure_count,),
    )
    conn.commit()


def test_pre_deadline_before_kickoff(db_conn):
    _seed_teams(db_conn)
    _seed_event(db_conn, 1, _FUTURE)
    _seed_fixture(db_conn, 1, 1, 1, 2, started=0, finished=0)
    _seed_healthy_fixtures_source(db_conn)

    state = compute_gw_lifecycle_state(db_conn)
    assert state.state == "PRE_DEADLINE"


def test_locked_after_deadline_before_kickoff(db_conn):
    _seed_teams(db_conn)
    _seed_event(db_conn, 1, _PAST)
    _seed_fixture(db_conn, 1, 1, 1, 2, started=0, finished=0)
    _seed_healthy_fixtures_source(db_conn)

    state = compute_gw_lifecycle_state(db_conn)
    assert state.state == "LOCKED"


def test_live_when_any_fixture_started(db_conn):
    _seed_teams(db_conn)
    _seed_event(db_conn, 1, _PAST)
    _seed_fixture(db_conn, 1, 1, 1, 2, started=1, finished=0)
    _seed_healthy_fixtures_source(db_conn)

    state = compute_gw_lifecycle_state(db_conn)
    assert state.state == "LIVE"
    assert state.any_started is True


def test_multi_match_stays_live_until_all_finished(db_conn):
    _seed_teams(db_conn)
    _seed_event(db_conn, 1, _PAST)
    _seed_fixture(db_conn, 1, 1, 1, 2, started=1, finished=1)  # finished
    _seed_fixture(db_conn, 2, 1, 3, 4, started=1, finished=0)  # still live
    _seed_healthy_fixtures_source(db_conn)

    state = compute_gw_lifecycle_state(db_conn)
    assert state.state == "LIVE"
    assert state.all_finished is False


def test_gw_finished_fresh_detection_with_no_pipeline_marker(db_conn):
    _seed_teams(db_conn)
    _seed_event(db_conn, 1, _PAST)
    _seed_fixture(db_conn, 1, 1, 1, 2, started=1, finished=1)
    _seed_fixture(db_conn, 2, 1, 3, 4, started=1, finished=1)
    _seed_healthy_fixtures_source(db_conn)

    state = compute_gw_lifecycle_state(db_conn)
    assert state.state == "GW_FINISHED"
    assert state.all_finished is True
    assert needs_post_gw_pipeline(state.state) is True


def test_next_gw_analysis_when_pipeline_started_but_not_done(db_conn):
    _seed_teams(db_conn)
    _seed_event(db_conn, 1, _PAST)
    _seed_fixture(db_conn, 1, 1, 1, 2, started=1, finished=1)
    _seed_healthy_fixtures_source(db_conn)
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('post_gw_pipeline_started_event', '1', 't0')"
    )
    db_conn.commit()

    state = compute_gw_lifecycle_state(db_conn)
    assert state.state == "NEXT_GW_ANALYSIS"
    assert needs_post_gw_pipeline(state.state) is True


def test_ready_for_next_deadline_when_pipeline_done(db_conn):
    _seed_teams(db_conn)
    _seed_event(db_conn, 1, _PAST)
    _seed_fixture(db_conn, 1, 1, 1, 2, started=1, finished=1)
    _seed_healthy_fixtures_source(db_conn)
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('post_gw_pipeline_done_event', '1', 't0')"
    )
    db_conn.commit()

    state = compute_gw_lifecycle_state(db_conn)
    assert state.state == "READY_FOR_NEXT_DEADLINE"
    assert needs_post_gw_pipeline(state.state) is False


def test_unknown_when_nothing_started_and_no_fixture_rows(db_conn):
    _seed_teams(db_conn)
    _seed_event(db_conn, 1, _FUTURE)
    _seed_healthy_fixtures_source(db_conn)
    # No fixture rows at all for this event.

    state = compute_gw_lifecycle_state(db_conn)
    assert state.state == "UNKNOWN"
    assert state.data_valid is False


# --- Direct-requirement tests: never declare GW_FINISHED on incomplete/missing/degraded data ---

def test_zero_fixture_rows_never_reaches_gw_finished(db_conn):
    _seed_teams(db_conn)
    _seed_event(db_conn, 1, _PAST)
    _seed_healthy_fixtures_source(db_conn)
    # deadline passed, but zero fixture rows exist - must not look "finished".

    state = compute_gw_lifecycle_state(db_conn)
    assert state.state != "GW_FINISHED"
    assert state.state in ("LOCKED", "UNKNOWN")


# Note: `fixtures.finished` is NOT NULL at the schema level (migration 0002),
# so a real NULL row can never exist via a normal INSERT - the
# `_fixture_data_is_trustworthy` non-NULL check is defensive redundancy
# against a hypothetical future schema relaxation or a malformed row from a
# different code path, not something reachable through this project's own
# real schema today. No test simulates it via direct insert for that reason -
# the schema itself already provides a stronger guarantee than any Python-
# level check could.


def test_degraded_fixtures_source_blocks_gw_finished_even_with_complete_data(db_conn):
    _seed_teams(db_conn)
    _seed_event(db_conn, 1, _PAST)
    _seed_fixture(db_conn, 1, 1, 1, 2, started=1, finished=1)
    _seed_healthy_fixtures_source(db_conn, failure_count=3)  # degraded

    state = compute_gw_lifecycle_state(db_conn)
    assert state.state != "GW_FINISHED"
    assert state.data_valid is False
    # A real fixture IS started, so this correctly still reads LIVE (per-row
    # evidence stays trustworthy even when the wider source health check fails).
    assert state.state == "LIVE"


def test_missing_source_health_row_blocks_gw_finished(db_conn):
    _seed_teams(db_conn)
    _seed_event(db_conn, 1, _PAST)
    _seed_fixture(db_conn, 1, 1, 1, 2, started=0, finished=1)
    # No source_health row seeded at all.

    state = compute_gw_lifecycle_state(db_conn)
    assert state.state != "GW_FINISHED"
    assert state.data_valid is False


def test_restart_recovery_two_independent_calls_agree(db_conn):
    _seed_teams(db_conn)
    _seed_event(db_conn, 1, _PAST)
    _seed_fixture(db_conn, 1, 1, 1, 2, started=1, finished=1)
    _seed_healthy_fixtures_source(db_conn)

    first = compute_gw_lifecycle_state(db_conn)
    second = compute_gw_lifecycle_state(db_conn)
    assert first == second  # pure, stateless - no hidden in-process memory
