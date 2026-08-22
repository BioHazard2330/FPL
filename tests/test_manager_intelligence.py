import pytest

from fpl_agent.models.manager_intelligence import manager_intelligence


def _seed_team(conn, team_id: int) -> None:
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?, 't0') "
        "ON CONFLICT DO NOTHING",
        (team_id, team_id, f"Team {team_id}", f"T{team_id}"),
    )
    conn.commit()


def _seed_player(conn, pid: int, team_id: int) -> None:
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0') ON CONFLICT DO NOTHING"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
        "VALUES (?,?,?,?,1,'a',0,'t0') ON CONFLICT DO NOTHING",
        (pid, pid, f"p{pid}", team_id),
    )
    conn.commit()


def _seed_match(conn, match_id: int, fotmob_id: str, kickoff: str, team_id: int, formation: str,
                 starters: list[int], sub_off_minutes: dict[int, int]) -> None:
    _seed_team(conn, team_id)
    _seed_team(conn, team_id + 100)  # a real opponent id, distinct
    conn.execute(
        "INSERT INTO match_intelligence "
        "(id, fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "source, retrieved_at, confidence) VALUES (?,?,?,?,?,?,'FULL_TIME','fotmob','t0','high')",
        (match_id, fotmob_id, "Premier League", kickoff, team_id, team_id + 100),
    )
    conn.execute(
        "INSERT INTO team_match_state (match_id, team_id, formation, source, retrieved_at, confidence) "
        "VALUES (?,?,?,'fotmob','t0','medium')",
        (match_id, team_id, formation),
    )
    for pid in starters:
        _seed_player(conn, pid, team_id)
        conn.execute(
            "INSERT INTO player_match_state (match_id, player_id, fotmob_player_id, team_id, started, "
            "substituted_off_minute, source, retrieved_at, confidence) "
            "VALUES (?,?,?,?,1,?,'fotmob','t0','medium')",
            (match_id, pid, str(pid), team_id, sub_off_minutes.get(pid)),
        )
    conn.commit()


def test_unknown_team_raises(db_conn):
    with pytest.raises(ValueError):
        manager_intelligence(db_conn, 99999)


def test_reports_insufficient_history_below_two_matches(db_conn):
    _seed_team(db_conn, 1)
    mi = manager_intelligence(db_conn, 1)
    assert mi.matches_observed == 0
    assert mi.note is not None
    assert mi.most_common_formation is None


def test_real_formation_frequency_and_rotation_rate(db_conn):
    _seed_match(db_conn, 1, "m1", "2026-08-01T15:00:00Z", team_id=1, formation="4-3-3",
                starters=[1, 2, 3], sub_off_minutes={1: 70})
    _seed_match(db_conn, 2, "m2", "2026-08-08T15:00:00Z", team_id=1, formation="4-3-3",
                starters=[1, 2, 4], sub_off_minutes={2: 60})

    mi = manager_intelligence(db_conn, 1)

    assert mi.matches_observed == 2
    assert mi.note is None
    assert mi.most_common_formation == "4-3-3"
    assert mi.formation_frequency == {"4-3-3": 2}
    # {1,2,3} vs {1,2,4}: intersection=2, union=4 -> jaccard distance 0.5
    assert mi.starting_xi_rotation_rate == 0.5
    assert mi.avg_first_substitution_minute == 65.0
