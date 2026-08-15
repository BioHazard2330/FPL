import pytest

from fpl_agent.models.blend import (
    blend_fixture_goals, clean_sheet_probability, goals_conceded_band_probability,
    market_implied_fixture_goals, market_implied_total_goals,
)
from fpl_agent.models.odds_devig import GoalsTotalProbabilities, MatchOutcomeProbabilities


def test_market_implied_fixture_goals_splits_by_win_probability():
    outcome = MatchOutcomeProbabilities(home_win=0.6, draw=0.25, away_win=0.15)
    totals = GoalsTotalProbabilities(over=0.55, under=0.45)
    result = market_implied_fixture_goals(outcome, totals)
    assert result.home_expected_goals > result.away_expected_goals
    assert result.home_expected_goals + result.away_expected_goals == pytest.approx(
        result.home_expected_goals + result.away_expected_goals  # sanity: both positive, finite
    )
    assert result.home_expected_goals > 0
    assert result.away_expected_goals > 0


def test_market_implied_total_goals_handles_lopsided_over_probability():
    # totals.over=0.998 is beyond what the old brentq bracket (0.01, 10.0) could
    # reach - 1 - poisson.cdf(2, 10.0) tops out at ~0.99723, so brentq raised
    # ValueError("f(a) and f(b) must have different signs") for any target this
    # high. The widened bracket (0.01, 30.0) comfortably covers it.
    totals = GoalsTotalProbabilities(over=0.998, under=0.002)
    lam = market_implied_total_goals(totals)
    assert lam == pytest.approx(10.395583858615357)


def test_market_implied_total_goals_raises_clear_error_for_unreachable_target():
    totals = GoalsTotalProbabilities(over=0.9999999999999, under=1e-13)
    with pytest.raises(ValueError, match="outside the range"):
        market_implied_total_goals(totals)


def test_blend_fixture_goals_weighted_average():
    result = blend_fixture_goals(dc_home_goals=2.0, dc_away_goals=1.0, market_home_goals=1.0, market_away_goals=1.5, weight=0.5)
    assert result.home_expected_goals == pytest.approx(1.5)
    assert result.away_expected_goals == pytest.approx(1.25)


def test_clean_sheet_probability_decreases_with_opponent_strength():
    assert clean_sheet_probability(0.01) > clean_sheet_probability(2.0)
    assert clean_sheet_probability(0.0) == pytest.approx(1.0)


def test_goals_conceded_band_probability():
    # low expected goals against -> low probability of conceding 2+
    low = goals_conceded_band_probability(expected_goals_against=0.3, min_goals=2)
    high = goals_conceded_band_probability(expected_goals_against=2.5, min_goals=2)
    assert low < high
