from fpl_agent.models import pundit_views as pv


def _player(conn, pid):
    conn.execute("INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'A','AAA','t')")
    conn.execute("INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (2,'D','DEF','Ds','t')")
    conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (?,?,?,1,2,'a',0,'t')", (pid, pid, f"P{pid}"))


def test_a_view_scales_only_its_player_and_its_gameweeks(db_conn):
    _player(db_conn, 1)
    pv.add_view(db_conn, 1, 0.5, 11, 13, "starter back from injury")
    assert pv.view_factor(db_conn, 1, 11) == 0.5 and pv.view_factor(db_conn, 1, 13) == 0.5
    assert pv.view_factor(db_conn, 1, 14) == 1.0 and pv.view_factor(db_conn, 2, 11) == 1.0


def test_a_factor_is_bounded_and_a_view_needs_a_reason(db_conn):
    _player(db_conn, 1)
    pv.add_view(db_conn, 1, 0.05, 11, 11, "out for the season, says the club")
    assert pv.view_factor(db_conn, 1, 11) == pv.FACTOR_MIN
    import pytest
    with pytest.raises(ValueError):
        pv.add_view(db_conn, 1, 0.8, 11, 11, "  ")


def test_a_revoked_view_stops_applying(db_conn):
    _player(db_conn, 1)
    vid = pv.add_view(db_conn, 1, 0.5, 11, 11, "rotation")
    pv.revoke(db_conn, vid)
    assert pv.view_factor(db_conn, 1, 11) == 1.0


def _outcome(conn, pid, event, predicted, actual):
    conn.execute("INSERT INTO prediction_outcomes (player_id, event, season, predicted_median, actual_points, predicted_at) VALUES (?,?,?,?,?,'t')",
                 (pid, event, "2026-27", predicted, actual))


def test_views_that_keep_missing_are_halved(db_conn):
    for pid in range(1, 12):
        _player(db_conn, pid)
        pv.add_view(db_conn, pid, 0.5, 11, 11, "a read that turns out wrong")
        _outcome(db_conn, pid, 11, 4.0, 6)
    assert pv.ledger(db_conn)["helped"] == 0
    assert pv.trust(db_conn) == 0.5
    assert pv.view_factor(db_conn, 1, 11) == 0.75


def test_views_that_help_keep_full_weight(db_conn):
    for pid in range(1, 12):
        _player(db_conn, pid)
        pv.add_view(db_conn, pid, 0.5, 11, 11, "a read that turns out right")
        _outcome(db_conn, pid, 11, 4.0, 1)
    assert pv.trust(db_conn) == 1.0 and pv.ledger(db_conn)["helped"] == 11


def test_a_new_view_makes_the_stored_plan_stale_for_that_reason(db_conn):
    from fpl_agent.optimization import week_plan

    _player(db_conn, 1)
    before = week_plan.calibration_id(db_conn)
    assert before == week_plan.calibration_id()
    pv.add_view(db_conn, 1, 0.5, 11, 11, "starter back")
    after = week_plan.calibration_id(db_conn)
    assert after != before and after.split("|views=")[0] == before
