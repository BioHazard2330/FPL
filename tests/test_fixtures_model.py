from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.models.fixtures import fixture_difficulty, fixture_window_score

_TEAMS = [
    {
        "id": 1, "code": 1, "name": "Home FC", "short_name": "HOM",
        "strength_overall_home": 3, "strength_overall_away": 3,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 1,
    },
    {
        "id": 2, "code": 2, "name": "Away FC", "short_name": "AWY",
        "strength_overall_home": 4, "strength_overall_away": 5,
        "strength_attack_home": 1300, "strength_attack_away": 1250,
        "strength_defence_home": 1200, "strength_defence_away": 1100, "pulse_id": 2,
    },
]

_EVENTS = [{
    "id": 1, "name": "GW1", "deadline_time": "2026-08-21T17:30:00Z", "deadline_time_epoch": 1,
    "finished": 0, "is_previous": 0, "is_current": 0, "is_next": 1,
    "average_entry_score": None, "highest_score": None,
}]

_FIXTURES = [{
    "id": 1, "code": 1, "event": 1, "kickoff_time": "2026-08-21T19:00:00Z",
    "team_h": 1, "team_a": 2, "team_h_score": None, "team_a_score": None,
    "team_h_difficulty": 2, "team_a_difficulty": 4, "finished": 0, "started": 0,
}]


def _seed(conn):
    now = "t0"
    _upsert_many(conn, "teams", _TEAMS, now)
    _upsert_many(conn, "events", _EVENTS, now)
    _upsert_many(conn, "fixtures", _FIXTURES, now)
    conn.commit()


def test_fixture_difficulty_uses_specific_strength_when_available(db_conn):
    _seed(db_conn)
    fd = fixture_difficulty(db_conn, 1)

    assert fd.team_h_attack_difficulty == 1100  # away team's away defence
    assert fd.team_h_defence_difficulty == 1250  # away team's away attack


def test_fixture_difficulty_falls_back_to_overall_when_zero(db_conn):
    _seed(db_conn)
    fd = fixture_difficulty(db_conn, 1)

    # home team's attack/defence are 0 -> falls back to strength_overall_home
    assert fd.team_a_attack_difficulty == 3
    assert fd.team_a_defence_difficulty == 3
    assert fd.used_fallback is True


def test_fixture_window_score_matches_single_fixture(db_conn):
    _seed(db_conn)
    window = fixture_window_score(db_conn, team_id=1, n_gw=1)

    assert window.fixture_count == 1
    assert window.avg_attack_difficulty == 1100
    assert window.avg_defence_difficulty == 1250


def test_fixture_window_score_empty_when_no_fixtures_in_range(db_conn):
    _seed(db_conn)
    window = fixture_window_score(db_conn, team_id=1, n_gw=1, from_event=5)

    assert window.fixture_count == 0
    assert window.avg_attack_difficulty == 0.0
