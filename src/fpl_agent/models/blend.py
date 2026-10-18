"""Blends the Dixon-Coles team-strength model's fixture-level expected goals
with market-implied expected goals derived from devigged bookmaker odds. The
market reacts to team news faster than a goals-history model can; the model
captures genuine team-strength signal odds sometimes misprice. DEFAULT_BLEND_
WEIGHT was fit on 1,512 stored matches (2022-23 to 2026-27) with a walk-forward
Dixon-Coles fit and the stored closing odds: mean log-likelihood of the actual
scoreline was -2.965 with no weight on the model, -2.967 at 0.2, -2.976 at 0.5
and -3.007 with the model alone, falling at every step. Closing odds are
sharper than the pulls this project stores, which can be hours old and miss
team news, so the weight is 0.2 and not 0; where a fixture has no odds the
model is used alone, as before.

market_implied_fixture_goals recovers (home, away) expected goals by fitting a
Poisson score grid to the devigged home/draw/away AND over-2.5 probabilities
at once. It used to split a total recovered from the over/under line between
the sides in proportion to the win probabilities, which ignores the draw
entirely. On the 1,920 stored matches that carry full odds and a result that
split overstated heavy home favourites' goals by 0.50 per match and understated
their opponents' by 0.43 (312 matches with a home-win probability above 65%),
and the joint fit cuts those biases to +0.09 and -0.03 and raises the mean
Poisson log-likelihood of the actual scoreline from -3.025 to -2.948. The old
split remains as the fallback when the fit cannot be solved.
"""
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from scipy.optimize import brentq, least_squares
from scipy.stats import poisson

from fpl_agent.models.odds_devig import GoalsTotalProbabilities, MatchOutcomeProbabilities

DEFAULT_BLEND_WEIGHT = 0.2  # weight on the Dixon-Coles model; (1 - weight) on market-implied


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
    return _total_goals_for_over(totals.over)


@lru_cache(maxsize=8192)
def _total_goals_for_over(target: float) -> float:
    """The inversion itself, cached on the over probability: every player
    projection for a fixture asks for the same fixture's total, and a
    dashboard build asked 12,937 times for about 400 distinct answers."""
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


_GRID = np.arange(11)
_FIT_LOWER, _FIT_UPPER = 0.05, 6.0


def _grid_probabilities(home_goals: float, away_goals: float) -> tuple[float, float, float, float]:
    joint = np.outer(poisson.pmf(_GRID, home_goals), poisson.pmf(_GRID, away_goals))
    return (
        float(np.tril(joint, -1).sum()), float(np.trace(joint)), float(np.triu(joint, 1).sum()),
        float(joint[np.add.outer(_GRID, _GRID) >= 3].sum()),
    )


@lru_cache(maxsize=8192)
def _fit_goals(home_win: float, draw: float, away_win: float, over: float, start_home: float, start_away: float) -> tuple[float, float]:
    """Least-squares fit of two Poisson means to four devigged probabilities (three
    outcomes, one total). Solved in log space inside [0.05, 6]; cached because
    every player projection for a fixture asks for the same fixture's goals."""
    def residual(log_params):
        ph, pd, pa, po = _grid_probabilities(*np.exp(log_params))
        return [ph - home_win, pd - draw, pa - away_win, po - over]

    start = np.log(np.clip([start_home, start_away], _FIT_LOWER, _FIT_UPPER))
    fit = least_squares(residual, start, bounds=(np.log(_FIT_LOWER), np.log(_FIT_UPPER)))
    home, away = np.exp(fit.x)
    return float(home), float(away)


def market_implied_fixture_goals(
    outcome: MatchOutcomeProbabilities, totals: GoalsTotalProbabilities
) -> BlendedFixtureGoals:
    total_goals = market_implied_total_goals(totals)
    strength_sum = outcome.home_win + outcome.away_win
    home_share = outcome.home_win / strength_sum if strength_sum else 0.5
    try:
        home, away = _fit_goals(
            round(outcome.home_win, 6), round(outcome.draw, 6), round(outcome.away_win, 6), round(totals.over, 6),
            total_goals * home_share, total_goals * (1 - home_share),
        )
        return BlendedFixtureGoals(home_expected_goals=home, away_expected_goals=away)
    except (ValueError, FloatingPointError):
        pass

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
