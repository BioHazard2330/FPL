from fpl_agent.backtesting import harness
from fpl_agent.backtesting.harness import (
    DifferentialBacktestResult,
    reconstruct_actual_points,
    run_backtest,
    save_backtest_run,
    score_differentials,
)


def _seed_reference_data(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (1,201,'Scorer',1,1,'a','2026-01-01T00:00:00Z')"
    )
    conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (1, 'Team A', 1), (2, 'Team B', NULL)")
    conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) VALUES "
        "('scoring.goals_scored.FWD','2024-25',1,'2024-08-01','fpl_api','4'), "
        "('scoring.assists','2024-25',1,'2024-08-01','fpl_api','3')"
    )


def _seed_matches(conn, dates):
    conn.executemany(
        "INSERT INTO match_results_history (season, match_date, home_team_id, away_team_id, home_goals, away_goals, source, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [("2024-25", d, 1, 2, 2, 1, "football_data", "2026-01-01T00:00:00Z") for d in dates],
    )


def _seed_player_matches(conn, player_id, dates, tag="a", goals=1):
    conn.executemany(
        "INSERT INTO player_match_stats_history "
        "(understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, "
        "minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'2026-01-01T00:00:00Z')",
        [
            (f"{tag}{i}", f"u{player_id}", player_id, 1, "2024-25", d, 90, goals, 0, 3, 0.6, 0.0, 1, 0, 0)
            for i, d in enumerate(dates)
        ],
    )


def _seed_season(conn):
    _seed_reference_data(conn)
    dates = [f"2024-09-{i + 1:02d}" for i in range(12)]
    _seed_matches(conn, dates)
    _seed_player_matches(conn, 1, dates, tag="m")
    conn.commit()


def test_reconstruct_actual_points_excludes_bonus(db_conn):
    _seed_season(db_conn)
    row = db_conn.execute("SELECT * FROM player_match_stats_history LIMIT 1").fetchone()
    actual = reconstruct_actual_points(db_conn, row, "2024-25")
    # 90 mins (2pt appearance) + 1 goal * 4 (FWD goal rule) = 6, no bonus available from this source
    assert actual == 6.0


def test_run_backtest_produces_result_and_beats_or_matches_baseline(db_conn):
    _seed_season(db_conn)
    result = run_backtest(db_conn, "2024-25", model_version="calibrated-v2")
    assert result.predictions_scored > 0
    assert result.mae >= 0
    assert result.baseline_mae >= 0


def test_save_backtest_run_persists_row(db_conn):
    _seed_season(db_conn)
    result = run_backtest(db_conn, "2024-25", model_version="calibrated-v2")
    run_id = save_backtest_run(db_conn, result)
    row = db_conn.execute("SELECT * FROM model_backtest_runs WHERE id=?", (run_id,)).fetchone()
    assert row["model_version"] == "calibrated-v2"
    assert row["season"] == "2024-25"


def test_fallback_prior_player_rounds_are_excluded_from_scoring(db_conn):
    """Players with <4 pre-cutoff matches fall back to expected_minutes(), which
    reads live (undated) squad status - scoring those would leak present-day data
    into a historical measurement, so they must be excluded, not silently mixed in.
    """
    _seed_reference_data(db_conn)
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (2,202,'Newcomer',1,1,'a','2026-01-01T00:00:00Z')"
    )
    dates = [f"2024-09-{i + 1:02d}" for i in range(12)]
    _seed_matches(db_conn, dates)
    # Round boundaries: round 1 starts 2024-09-01, round 2 starts 2024-09-11.
    _seed_player_matches(db_conn, 1, dates, tag="p1")  # 10 matches before the round-2 cutoff -> empirical
    _seed_player_matches(db_conn, 2, dates[8:], tag="p2")  # only 2 before the cutoff -> fallback_prior
    db_conn.commit()

    result = run_backtest(db_conn, "2024-25", model_version="calibrated-v2")

    # Only player 1's two round-2 rows are scorable. Player 2 also plays both of
    # those dates; if the fallback rows were scored this would be 4, not 2.
    assert result.predictions_scored == 2
    # Round 1: player 1 (10 rows) + player 2 (2 rows), all with no prior data.
    # Round 2: player 2's 2 rows.
    assert result.fallback_excluded_count == 14

    scored_only_empirical = run_backtest(db_conn, "2024-25", model_version="x")
    assert scored_only_empirical.predictions_scored + scored_only_empirical.fallback_excluded_count == 16


def test_round_own_results_do_not_reach_that_round_prediction(db_conn):
    """Behavioural counterpart to the spy test below: a player who scored nothing
    in every prior match, then 3 goals in each match of the scored round, must be
    predicted off the goalless history. If the round's own rows leaked into the
    prior, the error would collapse toward zero.
    """
    _seed_reference_data(db_conn)
    dates = [f"2024-09-{i + 1:02d}" for i in range(12)]
    _seed_matches(db_conn, dates)
    _seed_player_matches(db_conn, 1, dates[:10], tag="dry", goals=0)
    _seed_player_matches(db_conn, 1, dates[10:], tag="hot", goals=3)
    db_conn.commit()

    result = run_backtest(db_conn, "2024-25", model_version="calibrated-v2")

    # Only round 2 is scorable (round 1 has no prior data -> fallback -> excluded).
    assert result.predictions_scored == 2
    # Prior: 10 goalless 90-minute matches -> shrunk goal rate 0, p_full 1.0
    # -> predicted 2.0 (appearance only). Actual: 2 + 3 goals * 4 = 14.
    assert result.mae == 12.0
    assert result.baseline_mae == 12.0


def test_predictions_use_only_data_strictly_before_each_round_start(db_conn, monkeypatch):
    _seed_season(db_conn)
    seen = {"shrunk": [], "minutes": []}

    real_shrunk = harness.player_shrunk_rates
    real_minutes = harness.minutes_bucket_probabilities

    def spy_shrunk(conn, player_id, season, as_of_date=None):
        seen["shrunk"].append(as_of_date)
        return real_shrunk(conn, player_id, season, as_of_date=as_of_date)

    def spy_minutes(conn, player_id, season, as_of_date=None):
        seen["minutes"].append(as_of_date)
        return real_minutes(conn, player_id, season, as_of_date=as_of_date)

    monkeypatch.setattr(harness, "player_shrunk_rates", spy_shrunk)
    monkeypatch.setattr(harness, "minutes_bucket_probabilities", spy_minutes)

    run_backtest(db_conn, "2024-25", model_version="calibrated-v2")

    round_starts = {"2024-09-01", "2024-09-11"}
    # Every round is offered to the minutes model; only the non-excluded ones
    # reach the rate model (round 1 has no prior matches, so it is all fallback).
    assert set(seen["minutes"]) == round_starts
    assert set(seen["shrunk"]) == {"2024-09-11"}
    assert all(as_of in round_starts for as_of in seen["shrunk"])

    # The as_of_date handed to each round is that round's own earliest match date,
    # and the underlying models filter on `match_date < as_of_date`, so none of the
    # round's own matches (including the one being predicted) are visible.
    for as_of in round_starts:
        visible = db_conn.execute(
            "SELECT COUNT(*) AS n FROM player_match_stats_history WHERE season='2024-25' AND match_date >= ?",
            (as_of,),
        ).fetchone()["n"]
        assert visible > 0  # the round genuinely has matches that stay hidden from its own prediction
        probs = real_minutes(db_conn, 1, "2024-25", as_of_date=as_of)
        rates = real_shrunk(db_conn, 1, "2024-25", as_of_date=as_of)
        prior_matches = db_conn.execute(
            "SELECT COUNT(*) AS n FROM player_match_stats_history "
            "WHERE player_id=1 AND season='2024-25' AND match_date < ?",
            (as_of,),
        ).fetchone()["n"]
        assert rates["goals"].matches_played == round(prior_matches * 90 / 90, 2)
        assert (probs.source == "empirical") == (prior_matches >= 4)


def test_score_differentials_reports_insufficient_data_for_historical_season(db_conn):
    _seed_season(db_conn)  # no player_ownership_history rows seeded - real, honest gap
    result = score_differentials(db_conn, "2024-25", model_version="calibrated-v2")
    assert isinstance(result, DifferentialBacktestResult)
    assert result.insufficient_ownership_data is True
    assert result.differentials_scored == 0
    assert result.mean_delta_vs_template is None


def _insert_bonus_season_row(conn, player_id, season_name, bonus, minutes):
    conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, "
        "goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (?,?,?,0,0,0,0,0,0,?,0,0,0,0,0,0,50,55,'t0')",
        (player_id, season_name, minutes, bonus),
    )


def test_score_bonus_regression_reports_insufficient_data_when_no_multi_season_players(db_conn):
    _seed_reference_data(db_conn)  # existing helper in this file - teams/element_types/players/rules
    db_conn.commit()

    from fpl_agent.backtesting.harness import score_bonus_regression
    result = score_bonus_regression(db_conn)

    assert result.insufficient_data is True
    assert result.players_evaluated == 0


def test_score_bonus_regression_compares_shrunk_vs_naive_against_held_out_season(db_conn):
    _seed_reference_data(db_conn)
    # Player 1 (already seeded by _seed_reference_data as a FWD): three seasons.
    # Held-out (latest): 2024/25, real bonus90 = 15/900*90 = 1.5
    # Prior (naive baseline source): 2023/24, bonus90 = 1/900*90 = 0.1 - a big swing,
    # so naive (unshrunk carryover) will be a poor predictor of the held-out season.
    _insert_bonus_season_row(db_conn, 1, "2022/23", bonus=9, minutes=900)   # 0.9/90, forms part of the prior pool
    _insert_bonus_season_row(db_conn, 1, "2023/24", bonus=1, minutes=900)   # 0.1/90
    _insert_bonus_season_row(db_conn, 1, "2024/25", bonus=15, minutes=900)  # held out, actual 1.5/90
    db_conn.commit()

    from fpl_agent.backtesting.harness import score_bonus_regression
    result = score_bonus_regression(db_conn)

    assert result.insufficient_data is False
    assert result.players_evaluated == 1
    assert result.naive_mae == 1.4  # |0.1 - 1.5|
    # Shrunk prediction: prior season (2023/24) bonus90=0.1, matches=10; position
    # prior over seasons before 2024/25 = (9+1)/((900+900)/90) = 10/20 = 0.5;
    # shrink_rate(1.0, 900, 0.5) -> matches=10, raw=0.1,
    # shrunk=(10*0.1+10*0.5)/20=0.3 -> |0.3-1.5|=1.2
    assert result.shrunk_mae == 1.2
    assert result.shrunk_win_rate == 1.0  # 1.2 < 1.4, the only player in this holdout set
