"""Blends the Dixon-Coles team-strength model's fixture-level expected goals
with market-implied expected goals derived from devigged bookmaker odds. The
market reacts to team news faster than a goals-history model can; the model
captures genuine team-strength signal odds sometimes misprice. DEFAULT_BLEND_
WEIGHT is a fixed constant, not fit to anything yet - tune it once the
Pillar 0 backtest harness can score which weight predicts best.

market_implied_fixture_goals splits total-goals expectation (recovered from
the over/under-2.5 odds by inverting the Poisson CDF) between home/away
proportionally to devigged win probability - a documented heuristic, not a
fitted relationship; it ignores the draw probability's own information
content for simplicity.
"""
from dataclasses import dataclass

from scipy.optimize import brentq
from scipy.stats import poisson

from fpl_agent.models.odds_devig import GoalsTotalProbabilities, MatchOutcomeProbabilities

DEFAULT_BLEND_WEIGHT = 0.5  # weight on the Dixon-Coles model; (1 - weight) on market-implied


@dataclass(frozen=True)
class BlendedFixtureGoals:
    home_expected_goals: float
    away_expected_goals: float


def market_implied_total_goals(totals: GoalsTotalProbabilities) -> float:
    """Inverts P(total goals > 2.5) back to a single Poisson mean for total match goals."""
    target = totals.over
    return brentq(lambda lam: (1 - poisson.cdf(2, lam)) - target, 0.01, 10.0)


def market_implied_fixture_goals(
    outcome: MatchOutcomeProbabilities, totals: GoalsTotalProbabilities
) -> BlendedFixtureGoals:
    total_goals = market_implied_total_goals(totals)
    strength_sum = outcome.home_win + outcome.away_win
    home_share = outcome.home_win / strength_sum if strength_sum else 0.5
    return BlendedFixtureGoals(
        home_expected_goals=total_goals * home_share,
        away_expected_goals=total_goals * (1 - home_share),
    )


def blend_fixture_goals(
    dc_home_goals: float, dc_away_goals: float,
    market_home_goals: float, market_away_goals: float,
    weight: float = DEFAULT_BLEND_WEIGHT,
) -> BlendedFixtureGoals:
    return BlendedFixtureGoals(
        home_expected_goals=weight * dc_home_goals + (1 - weight) * market_home_goals,
        away_expected_goals=weight * dc_away_goals + (1 - weight) * market_away_goals,
    )


def clean_sheet_probability(opponent_expected_goals: float) -> float:
    return float(poisson.pmf(0, opponent_expected_goals))


def goals_conceded_band_probability(expected_goals_against: float, min_goals: int) -> float:
    """P(goals conceded >= min_goals) - feeds the -1-per-2-conceded penalty bands."""
    return float(1 - poisson.cdf(min_goals - 1, expected_goals_against))
