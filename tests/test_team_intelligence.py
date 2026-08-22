import pytest

from fpl_agent.models.team_intelligence import team_qualitative_intelligence

from test_qualitative_trends import _seed_match, _seed_observation


def test_unknown_team_raises(db_conn):
    with pytest.raises(ValueError):
        team_qualitative_intelligence(db_conn, 99999)


def test_team_with_no_analysis_is_honestly_empty(db_conn):
    _seed_match(db_conn, 1, "m1", "2026-08-01T15:00:00Z")  # seeds teams 1 and 2

    ti = team_qualitative_intelligence(db_conn, 1)

    assert ti.team_name == "Team A"
    assert ti.current_tactical_signal is None
    assert ti.trends == []


def test_team_qualitative_intelligence_combines_state_and_trends(db_conn):
    _seed_match(db_conn, 1, "m1", "2026-08-01T15:00:00Z")
    _seed_observation(db_conn, 1, "team", 1, "TEAM_ATTACK", "POSITIVE")
    db_conn.execute(
        "INSERT INTO team_qualitative_state "
        "(team_id, match_id, tactical_signal, attacking_signal, defensive_signal, generated_at) "
        "VALUES (1, 1, 'high press', 'more direct', 'higher line', 't0')"
    )
    db_conn.commit()

    ti = team_qualitative_intelligence(db_conn, 1)

    assert ti.current_tactical_signal == "high press"
    assert ti.current_attacking_signal == "more direct"
    assert len(ti.trends) == 1
    assert ti.trends[0].signal == "TEAM_ATTACK"
    assert ti.trends[0].label == "NEW_SIGNAL"
