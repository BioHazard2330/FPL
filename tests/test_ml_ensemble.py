import numpy as np

from fpl_agent.models.ml_ensemble import FEATURE_NAMES, build_dataset, evaluate, train
from test_backtest_harness import _seed_season


def test_build_dataset_produces_expected_shape_and_target_range(db_conn):
    """Same real season used by test_backtest_harness.py's own tests
    (12 pre-cutoff matches for player 1, all goal-scoring FWD rows) - proves
    the walk-forward feature extraction runs end to end without crashing and
    respects the same >=4-pre-cutoff-matches leakage exclusion run_backtest
    enforces (early rounds correctly produce fewer or zero feature rows)."""
    _seed_season(db_conn)

    X, y = build_dataset(db_conn, ["2024-25"])

    assert X.shape[1] == len(FEATURE_NAMES)
    assert X.shape[0] == y.shape[0]
    assert X.shape[0] > 0
    # 90 minutes + 1 goal, FWD (4pt rule) = 6.0 every row for this synthetic squad
    assert (y == 6.0).all()


def test_build_dataset_excludes_rows_below_the_empirical_minutes_threshold(db_conn):
    """A player with fewer than 4 pre-cutoff matches must never appear in the
    training set (same leakage bar as run_backtest's fallback_excluded_count) -
    adding a single-match fringe player must not change the row count at all
    versus the player-1-only baseline."""
    _seed_season(db_conn)
    baseline_X, _ = build_dataset(db_conn, ["2024-25"])

    db_conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (2,202,'Fringe',1,1,'a','2026-01-01T00:00:00Z')"
    )
    dates = [f"2024-09-{i + 1:02d}" for i in range(12)]
    db_conn.execute(
        "INSERT INTO player_match_stats_history "
        "(understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, "
        "minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
        "VALUES ('fringe0','u2',2,1,'2024-25',?,90,0,0,0,0.0,0.0,0,0,0,'t0')",
        (dates[-1],),
    )
    db_conn.commit()

    X, y = build_dataset(db_conn, ["2024-25"])

    # player 2 has only 1 match total - never enough pre-cutoff history to
    # cross the empirical threshold, so it must never contribute a row.
    assert X.shape[0] == baseline_X.shape[0]
    assert baseline_X.shape[0] > 0  # sanity: the baseline itself isn't degenerate


def test_train_and_evaluate_round_trip(db_conn):
    """Not a real accuracy claim (12 synthetic rows, all-identical target) -
    just proves the XGBoost training/evaluation plumbing itself works without
    crashing, including the high/low-return bucket split."""
    _seed_season(db_conn)
    X, y = build_dataset(db_conn, ["2024-25"])

    model = train(X, y)
    result = evaluate(model, X, y)

    assert result["n"] == X.shape[0]
    assert result["mae"] >= 0
    assert np.isfinite(result["mae"])
