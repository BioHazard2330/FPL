"""Real live win probability (2026-09-10) - the one broadcast graphic
football almost never shows, despite being standard in basketball/NFL
coverage: given the actual current score and how much of the match is
left, what's the real chance each side wins.

Built entirely from infrastructure this project already has and already
trusts for FPL projections: the fitted Dixon-Coles team-strength model
(`models/team_strength_dc.py`), reused via the SAME cached-per-day fitter
(`expected_points.py::_get_or_fit_dc_model`) the projection pipeline
already relies on - never a second, independently-fitted model that could
silently disagree with it.

**Real, disclosed methodology, deliberately simple for v1**: the model's
own real pre-match expected goals (`expected_goals()`) are scaled down by
the real fraction of the match still to play, then treated as independent
Poisson arrivals for the remainder - summed jointly against the real
current score to get P(home)/P(draw)/P(away). Two real, disclosed
simplifications, not hidden:

1. No re-application of Dixon-Coles' own low-score correlation (rho) term
   to the scaled-down remaining-time lambdas - that correction was fitted
   for a FULL 90-minute match, and re-deriving it for an arbitrary partial
   window needs its own real validation this project hasn't done. Plain
   independent Poisson is used for the remainder instead - a small, honest
   underestimate of how often the match stays goalless the rest of the way,
   not a fabricated precision.
2. Time-decay only, not live-performance-adjusted: a team dominating a
   match 0-0 gets the same remaining-goal expectation as a team being
   battered 0-0 - the real pre-match rating scaled by time, nothing from
   the match itself (momentum, xG so far) feeds back in. A real, scoped v2
   would blend in-match xG accumulation; not attempted here.

Both limitations are surfaced in the returned dict's own `basis` field
rather than silently baked into a number that reads as more certain than
it is.
"""
import sqlite3
from dataclasses import dataclass
from math import exp, factorial

from fpl_agent.ingestion.market_identity import get_or_create_market_team
from fpl_agent.models.team_strength_dc import expected_goals as dc_expected_goals

_MAX_REMAINING_GOALS = 8  # real cap - P(a side scores 9+ in the time actually left) is negligible at any real remaining-lambda this model produces
_MATCH_LENGTH_MINUTES = 90.0


@dataclass(frozen=True)
class WinProbability:
    home_win_pct: float
    draw_pct: float
    away_win_pct: float
    remaining_home_xg: float
    remaining_away_xg: float
    basis: str


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return exp(-lam) * (lam**k) / factorial(k)


def remaining_win_probability(
    conn: sqlite3.Connection,
    home_team_id: int,
    away_team_id: int,
    home_score: int,
    away_score: int,
    minutes_elapsed: float,
    as_of_date: str,
) -> WinProbability | None:
    """Real per-request read, not a background computation - cheap once the
    model itself is cached (a live poll asking this every ~15s pays only the
    real `expected_goals()` lookup + a bounded double sum, no refit).
    Returns `None` (never a guessed 33/33/33) when the model can't cover
    both real teams - a genuinely new club with no fitted rating yet, or too
    little historical data leaguewide."""
    from fpl_agent.models.expected_points import _fpl_team_name, _get_or_fit_dc_model

    home_market_id = get_or_create_market_team(conn, "fpl", _fpl_team_name(conn, home_team_id))
    away_market_id = get_or_create_market_team(conn, "fpl", _fpl_team_name(conn, away_team_id))
    dc_model = _get_or_fit_dc_model(conn, as_of_date)
    if dc_model is None or home_market_id not in dc_model.teams or away_market_id not in dc_model.teams:
        return None

    lam_full, mu_full = dc_expected_goals(dc_model, home_market_id, away_market_id)
    remaining_fraction = max(0.0, min(1.0, (_MATCH_LENGTH_MINUTES - minutes_elapsed) / _MATCH_LENGTH_MINUTES))
    lam_rem = lam_full * remaining_fraction
    mu_rem = mu_full * remaining_fraction

    home_pmf = [_poisson_pmf(k, lam_rem) for k in range(_MAX_REMAINING_GOALS)]
    away_pmf = [_poisson_pmf(k, mu_rem) for k in range(_MAX_REMAINING_GOALS)]

    home_win = draw = away_win = 0.0
    for rh, p_rh in enumerate(home_pmf):
        final_home = home_score + rh
        for ra, p_ra in enumerate(away_pmf):
            p = p_rh * p_ra
            final_away = away_score + ra
            if final_home > final_away:
                home_win += p
            elif final_home == final_away:
                draw += p
            else:
                away_win += p

    total = home_win + draw + away_win
    if total <= 0:
        return None
    return WinProbability(
        home_win_pct=round(home_win / total * 100, 1),
        draw_pct=round(draw / total * 100, 1),
        away_win_pct=round(away_win / total * 100, 1),
        remaining_home_xg=round(lam_rem, 3),
        remaining_away_xg=round(mu_rem, 3),
        basis="time-decayed pre-match Dixon-Coles rating, independent Poisson for the remainder - not live-performance-adjusted",
    )
