import pytest

from fpl_agent.models.player_intelligence import player_intelligence, squad_player_intelligence

from test_qualitative_trends import _seed_match, _seed_observation


def _seed_player(conn, pid: int, team_id: int = 1) -> None:
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?, 't0') "
        "ON CONFLICT DO NOTHING",
        (team_id, team_id, f"Team {team_id}", f"T{team_id}"),
    )
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0') ON CONFLICT DO NOTHING"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
        "VALUES (?,?,?,?,1,'a',0,'t0')",
        (pid, pid, f"p{pid}", team_id),
    )
    conn.commit()


def _seed_qualitative_state(conn, player_id: int, match_id: int) -> None:
    conn.execute(
        "INSERT INTO player_qualitative_state "
        "(player_id, match_id, role, tactical_signal, fpl_outlook, confidence, generated_at) "
        "VALUES (?,?,'starting striker','high press target','buy candidate','medium','t0')",
        (player_id, match_id),
    )
    conn.commit()


def test_unknown_player_raises(db_conn):
    with pytest.raises(ValueError):
        player_intelligence(db_conn, 99999)


def test_player_with_no_analysis_is_honestly_empty(db_conn):
    _seed_player(db_conn, 1)

    pi = player_intelligence(db_conn, 1)

    assert pi.web_name == "p1"
    assert pi.current_role is None
    assert pi.trends == []


def test_player_intelligence_combines_current_state_and_trends(db_conn):
    _seed_player(db_conn, 1)
    _seed_match(db_conn, 1, "m1", "2026-08-01T15:00:00Z")
    _seed_match(db_conn, 2, "m2", "2026-08-08T15:00:00Z")
    _seed_observation(db_conn, 1, "player", 1, "ROLE", "POSITIVE")
    _seed_observation(db_conn, 2, "player", 1, "ROLE", "POSITIVE")
    _seed_qualitative_state(db_conn, 1, match_id=2)

    pi = player_intelligence(db_conn, 1)

    assert pi.current_role == "starting striker"
    assert pi.last_match_id == 2
    assert len(pi.trends) == 1
    assert pi.trends[0].label == "PERSISTENT_TREND"


def test_squad_player_intelligence_omits_players_with_no_real_evidence(db_conn):
    _seed_player(db_conn, 1)
    _seed_player(db_conn, 2)
    _seed_match(db_conn, 1, "m1", "2026-08-01T15:00:00Z")
    _seed_observation(db_conn, 1, "player", 1, "ROLE", "POSITIVE")
    # player 2 gets no evidence at all

    result = squad_player_intelligence(db_conn, [1, 2])

    assert [pi.player_id for pi in result] == [1]
