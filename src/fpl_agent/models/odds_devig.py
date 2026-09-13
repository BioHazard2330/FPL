"""Proportional overround removal - normalizes implied probabilities (1/odds)
to sum to 1. The simplest defensible devig method; doesn't correct for
bookmaker favorite-longshot bias the way Shin's method does, but this project
has no calibration data yet to justify the extra tunable parameter Shin's
method needs. Revisit once the Pillar 0 backtest harness can score whether a
fancier devig method actually predicts better."""
from dataclasses import dataclass


@dataclass(frozen=True)
class MatchOutcomeProbabilities:
    home_win: float
    draw: float
    away_win: float


@dataclass(frozen=True)
class GoalsTotalProbabilities:
    over: float
    under: float


def _check_odds(*values: float) -> None:
    if any(v <= 1.0 for v in values):
        raise ValueError("decimal odds must be > 1.0")


def devig_match_odds(home_odds: float, draw_odds: float, away_odds: float) -> MatchOutcomeProbabilities:
    _check_odds(home_odds, draw_odds, away_odds)
    raw = [1 / home_odds, 1 / draw_odds, 1 / away_odds]
    overround = sum(raw)
    return MatchOutcomeProbabilities(*(p / overround for p in raw))


def devig_totals_odds(over_odds: float, under_odds: float) -> GoalsTotalProbabilities:
    _check_odds(over_odds, under_odds)
    raw_over, raw_under = 1 / over_odds, 1 / under_odds
    overround = raw_over + raw_under
    return GoalsTotalProbabilities(raw_over / overround, raw_under / overround)


def devig_two_outcome_prop(yes_odds: float, no_odds: float | None) -> tuple[float, float | None]:
    """Real per-player two-outcome devig (e.g. a real anytime-goalscorer
    Yes/No price pair) - identical proportional-overround math to
    `devig_totals_odds` above (one player's own Yes/No is a genuine
    complementary pair, same shape as an Over/Under line), reused rather
    than duplicated when this was folded in from the-odds-api.com-specific
    `player_odds_source.py` (removed 2026-09-13 along with that dead
    vendor). Honestly returns `(raw, None)` when no real complementary
    price exists to devig against, rather than fabricating a devig from one
    side alone - the one real difference from `devig_totals_odds`, which
    requires both sides."""
    raw = round(1 / yes_odds, 4)
    if not no_odds:
        return raw, None
    return raw, round(devig_totals_odds(yes_odds, no_odds).over, 4)
