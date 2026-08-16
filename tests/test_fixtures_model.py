from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.models.fixtures import fixture_difficulty, fixture_window_score, detect_blank_double_gws

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


def _seed_teams_and_fixtures(conn):
    # 3 teams. GW10: team1 vs team2 (team3 has no GW10 fixture -> blank). GW11:
    # team1 vs team3, then team1 vs team2 again (team1 has two GW11 fixtures ->
    # double; team2 and team3 each have exactly one GW11 fixture -> normal).
    conn.executemany(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,?)",
        [(1, 100, "Team A", "TMA", "t0"), (2, 101, "Team B", "TMB", "t0"), (3, 102, "Team C", "TMC", "t0")],
    )
    conn.executemany(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, average_entry_score, highest_score, updated_at) VALUES (?,?,?,?,0,0,0,0,?,?,?)",
        [
            (10, "GW10", "2026-08-28T17:30:00Z", 100, None, None, "t0"),
            (11, "GW11", "2026-09-04T17:30:00Z", 200, None, None, "t0"),
        ],
    )
    conn.executemany(
        "INSERT INTO fixtures (id, code, event, team_h, team_a, finished, started, updated_at) VALUES (?,?,?,?,?,0,0,'t0')",
        [
            (1, 1, 10, 1, 2),  # GW10: team1 vs team2
            (2, 2, 11, 1, 3),  # GW11: team1 vs team3
            (3, 3, 11, 1, 2),  # GW11: team1 vs team2 again -> team1's double
        ],
    )
    conn.commit()


def test_detects_blank_and_double(db_conn):
    _seed_teams_and_fixtures(db_conn)

    anomalies = detect_blank_double_gws(db_conn, start_event=10, n_gw=2)

    by_key = {(a.event, a.team_id): a.kind for a in anomalies}
    assert by_key[(10, 3)] == "blank"   # team 3 has no GW10 fixture
    assert by_key[(11, 1)] == "double"  # team 1 has two GW11 fixtures (ids 2 and 3)
    assert (11, 2) not in by_key        # team 2 has exactly one GW11 fixture - not an anomaly
