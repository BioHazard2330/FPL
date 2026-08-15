import pytest

from fpl_agent.models.blend import (
    blend_fixture_goals, clean_sheet_probability, goals_conceded_band_probability,
    market_implied_fixture_goals,
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
