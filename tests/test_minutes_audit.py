from fpl_agent.backtesting.minutes_audit import (
    CONGESTED_SCHEDULE,
    ESTABLISHED,
    NEW_OR_FIRST_APPEARANCE,
    RETURNING_AFTER_ABSENCE,
    ROTATION,
    SUBSTITUTE,
    audit_minutes_by_segment,
    classify_round_segment,
)

_SEASON = "2024-25"


def _seed_base(conn):
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Team A','TMA','t0')")
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (2,2,'Team B','TMB','t0')")
    conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (1,'Team A',1)")
    conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (2,'Team B',2)")
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Midfielder','MID','Midfielders','t0')"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (1,1,'P1',1,1,'a','t0')"
    )


def _seed_match_row(conn, player_id, match_date, minutes):
    conn.execute(
        "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, "
        "market_team_id, season, match_date, minutes, goals, assists, shots, xg, xa, key_passes, "
        "yellow_cards, red_cards, retrieved_at) VALUES (?,?,?,1,?,?,?,0,0,0,0.0,0.0,0,0,0,'t0')",
        (f"m_{match_date}", "u1", player_id, _SEASON, match_date, minutes),
    )


def _seed_team_match(conn, match_date):
    conn.execute(
        "INSERT INTO match_results_history (season, match_date, home_team_id, away_team_id, home_goals, "
        "away_goals, source, retrieved_at) VALUES (?,?,1,2,1,0,'test','t0')",
        (_SEASON, match_date),
    )


def test_classify_round_segment_new_or_first_appearance_with_no_prior_rows(db_conn):
    _seed_base(db_conn)
    db_conn.commit()

    assert classify_round_segment(db_conn, 1, 1, _SEASON, "2024-09-01") == NEW_OR_FIRST_APPEARANCE


def test_classify_round_segment_established_starter_from_trailing_median(db_conn):
    _seed_base(db_conn)
    for d in ("2024-08-01", "2024-08-08", "2024-08-15", "2024-08-22", "2024-08-29"):
        _seed_match_row(db_conn, 1, d, 90)
    db_conn.commit()

    assert classify_round_segment(db_conn, 1, 1, _SEASON, "2024-09-05") == ESTABLISHED


def test_classify_round_segment_rotation_player_from_trailing_median(db_conn):
    _seed_base(db_conn)
    for d in ("2024-08-01", "2024-08-08", "2024-08-15", "2024-08-22", "2024-08-29"):
        _seed_match_row(db_conn, 1, d, 30)
    db_conn.commit()

    assert classify_round_segment(db_conn, 1, 1, _SEASON, "2024-09-05") == ROTATION


def test_classify_round_segment_substitute_from_trailing_median(db_conn):
    _seed_base(db_conn)
    for d in ("2024-08-01", "2024-08-08", "2024-08-15", "2024-08-22", "2024-08-29"):
        _seed_match_row(db_conn, 1, d, 10)
    db_conn.commit()

    assert classify_round_segment(db_conn, 1, 1, _SEASON, "2024-09-05") == SUBSTITUTE


def test_classify_round_segment_returning_after_absence(db_conn):
    _seed_base(db_conn)
    _seed_match_row(db_conn, 1, "2024-08-01", 90)
    db_conn.commit()  # real 30+ day gap to the scored round

    assert classify_round_segment(db_conn, 1, 1, _SEASON, "2024-09-15") == RETURNING_AFTER_ABSENCE


def test_classify_round_segment_congested_schedule(db_conn):
    _seed_base(db_conn)
    _seed_match_row(db_conn, 1, "2024-09-01", 90)
    _seed_team_match(db_conn, "2024-09-01")
    db_conn.commit()  # a real team fixture 2 days before the scored round

    assert classify_round_segment(db_conn, 1, 1, _SEASON, "2024-09-03") == CONGESTED_SCHEDULE


def test_audit_minutes_by_segment_raises_without_real_matches(db_conn):
    import pytest
    with pytest.raises(ValueError, match="no match_results_history rows"):
        audit_minutes_by_segment(db_conn, "1999-00")


def test_audit_minutes_by_segment_produces_real_per_segment_results(db_conn):
    _seed_base(db_conn)
    dates = [f"2024-09-{i + 1:02d}" for i in range(12)]
    for d in dates:
        _seed_team_match(db_conn, d)
        _seed_match_row(db_conn, 1, d, 90)
    db_conn.commit()

    results = audit_minutes_by_segment(db_conn, _SEASON)

    assert results  # at least one real segment scored
    for segment, r in results.items():
        assert r.sample_size > 0
        assert r.model_mae >= 0
