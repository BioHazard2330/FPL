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


_LAMBDA_LOWER = 0.01
_LAMBDA_UPPER = 30.0


def market_implied_total_goals(totals: GoalsTotalProbabilities) -> float:
    """Inverts P(total goals > 2.5) back to a single Poisson mean for total match goals.

    Solved by bisecting lam in [0.01, 30.0]. At those endpoints
    1 - poisson.cdf(2, lam) is ~1.65e-7 and ~0.9999999999549898, so any
    totals.over in that band - which covers every practically-reachable
    devigged over/under-2.5 probability, including heavily lopsided real
    markets - resolves. totals.over outside that band would require an
    over/under line no real bookmaker would price.
    """
    target = totals.over
    f_lower = (1 - poisson.cdf(2, _LAMBDA_LOWER)) - target
    f_upper = (1 - poisson.cdf(2, _LAMBDA_UPPER)) - target
    if f_lower * f_upper > 0:
        raise ValueError(
            f"totals.over={target!r} is outside the range this Poisson total-goals "
            f"inversion can solve (bracket covers ~1.65e-7 to ~0.9999999999549898); "
            f"this implies an over/under market too lopsided for any real bookmaker "
            f"to price."
        )
    return brentq(lambda lam: (1 - poisson.cdf(2, lam)) - target, _LAMBDA_LOWER, _LAMBDA_UPPER)


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
