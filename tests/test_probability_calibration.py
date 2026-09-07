import math

import pytest

from fpl_agent.backtesting.probability_calibration import (
    _poisson_prob_at_least,
    validate_goal_probability_calibration,
)
from test_backtest_harness import _seed_season


def test_poisson_prob_at_least_matches_closed_form():
    lam = 0.5
    assert _poisson_prob_at_least(lam, 1) == pytest.approx(1 - math.exp(-lam))
    p0 = math.exp(-lam)
    assert _poisson_prob_at_least(lam, 2) == pytest.approx(1 - p0 - lam * p0)


def test_poisson_prob_at_least_zero_rate_is_zero_probability():
    assert _poisson_prob_at_least(0.0, 1) == 0.0


def test_poisson_prob_at_least_rejects_unsupported_threshold():
    with pytest.raises(ValueError, match="unsupported threshold"):
        _poisson_prob_at_least(0.5, 3)


def test_validate_goal_probability_calibration_produces_a_real_result(db_conn):
    _seed_season(db_conn)

    result = validate_goal_probability_calibration(db_conn, "2024-25", threshold=1)

    assert result.season == "2024-25"
    assert result.threshold == 1
    assert result.sample_size > 0
    assert 0.0 <= result.brier_score <= 1.0
    assert len(result.bins) > 0
    for b in result.bins:
        assert 0.0 <= b.predicted_mean <= 1.0
        assert 0.0 <= b.realized_frequency <= 1.0
        assert b.sample_size > 0


def test_validate_goal_probability_calibration_empty_when_nothing_crosses_the_empirical_gate(db_conn):
    from test_backtest_harness import _seed_matches, _seed_player_matches, _seed_reference_data

    _seed_reference_data(db_conn)
    dates = ["2024-09-01", "2024-09-02"]
    _seed_matches(db_conn, dates)
    _seed_player_matches(db_conn, 1, dates, tag="m")
    db_conn.commit()

    result = validate_goal_probability_calibration(db_conn, "2024-25")

    assert result.sample_size == 0
    assert result.bins == ()
    assert result.fallback_excluded_count > 0
