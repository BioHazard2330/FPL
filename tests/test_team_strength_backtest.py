import pytest

from fpl_agent.backtesting.team_strength_backtest import TeamStrengthBacktestResult, score_team_strength


def _seed_market_teams(conn):
    conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (1, 'Team A', NULL), (2, 'Team B', NULL)")
    conn.commit()


def _seed_matches(conn, season, dates, home_goals=2, away_goals=1):
    _seed_market_teams(conn)
    conn.executemany(
        "INSERT INTO match_results_history (season, match_date, home_team_id, away_team_id, "
        "home_goals, away_goals, source, retrieved_at) VALUES (?,?,?,?,?,?,'test','t0')",
        [(season, d, 1, 2, home_goals, away_goals) for d in dates],
    )
    conn.commit()


def test_score_team_strength_fits_and_scores_a_real_later_round(db_conn):
    """30 distinct match dates, one match each, ROUND_SIZE=10 -> 3 rounds.
    Rounds 0/1 (fewer than 20 strictly-prior matches) must be honestly
    skipped, never fit on a too-thin sample; round 2 (20 strictly-prior
    matches available) must fit and score its own 10 real matches."""
    dates = [f"2024-0{1 + i // 28}-{1 + i % 28:02d}" for i in range(30)]
    _seed_matches(db_conn, "2024-25", dates)

    result = score_team_strength(db_conn, "2024-25", half_life_days=365.0)

    assert result.season == "2024-25"
    assert result.rounds_evaluated == 1
    assert result.goals_scored == 20  # 10 matches * 2 (home + away) error terms
    assert result.goals_mae >= 0.0


def test_score_team_strength_raises_for_an_unknown_season(db_conn):
    with pytest.raises(ValueError, match="no match_results_history rows"):
        score_team_strength(db_conn, "1999-00")


def test_score_team_strength_result_is_a_real_dataclass(db_conn):
    dates = [f"2024-0{1 + i // 28}-{1 + i % 28:02d}" for i in range(30)]
    _seed_matches(db_conn, "2024-25", dates)

    result = score_team_strength(db_conn, "2024-25", half_life_days=180.0, ridge_lambda=1.0)

    assert isinstance(result, TeamStrengthBacktestResult)
    assert result.half_life_days == 180.0
    assert result.ridge_lambda == 1.0
