from fpl_agent.models.qualitative_trends import classify_direction_history, signal_trends_for_subject


def test_single_observation_is_new_signal():
    assert classify_direction_history(["POSITIVE"]) == "NEW_SIGNAL"


def test_two_agreeing_observations_are_persistent():
    assert classify_direction_history(["POSITIVE", "POSITIVE"]) == "PERSISTENT_TREND"


def test_two_disagreeing_observations_are_a_reversal():
    assert classify_direction_history(["NEGATIVE", "POSITIVE"]) == "REVERSAL"


def test_two_agree_but_a_third_disagrees_is_noise():
    assert classify_direction_history(["POSITIVE", "POSITIVE", "NEGATIVE"]) == "NOISE"


def test_three_agreeing_observations_are_persistent():
    assert classify_direction_history(["POSITIVE", "POSITIVE", "POSITIVE"]) == "PERSISTENT_TREND"


def _seed_match(conn, match_id: int, fotmob_id: str, kickoff: str) -> None:
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Team A','TMA','t0') "
        "ON CONFLICT DO NOTHING"
    )
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (2,2,'Team B','TMB','t0') "
        "ON CONFLICT DO NOTHING"
    )
    conn.execute(
        "INSERT INTO match_intelligence "
        "(id, fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "source, retrieved_at, confidence) "
        "VALUES (?,?,?,?,1,2,'FULL_TIME','fotmob','t0','high')",
        (match_id, fotmob_id, "Premier League", kickoff),
    )
    conn.commit()


def _seed_observation(conn, match_id: int, subject_type: str, subject_id: int, signal: str, direction: str, phase="FULL_TIME") -> None:
    conn.execute(
        "INSERT INTO match_observations "
        "(match_id, subject_type, subject_id, observation_type, observed, fpl_direction, fpl_signal, "
        "confidence, created_at, phase) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (match_id, subject_type, subject_id, "ROLE", "real observed text", direction, signal, "medium", "t0", phase),
    )
    conn.commit()


def test_signal_trends_for_subject_groups_by_signal_and_orders_by_kickoff(db_conn):
    _seed_match(db_conn, 1, "m1", "2026-08-01T15:00:00Z")
    _seed_match(db_conn, 2, "m2", "2026-08-08T15:00:00Z")
    _seed_observation(db_conn, 1, "player", 99, "ROLE", "POSITIVE")
    _seed_observation(db_conn, 2, "player", 99, "ROLE", "POSITIVE")

    trends = signal_trends_for_subject(db_conn, "player", 99)

    assert len(trends) == 1
    assert trends[0].signal == "ROLE"
    assert trends[0].label == "PERSISTENT_TREND"
    assert trends[0].sample_size == 2


def test_signal_trends_excludes_halftime_observations(db_conn):
    _seed_match(db_conn, 1, "m1", "2026-08-01T15:00:00Z")
    _seed_observation(db_conn, 1, "player", 99, "ROLE", "POSITIVE", phase="HALFTIME")

    trends = signal_trends_for_subject(db_conn, "player", 99)

    assert trends == []


def test_signal_trends_returns_nothing_for_an_unobserved_subject(db_conn):
    assert signal_trends_for_subject(db_conn, "player", 12345) == []
