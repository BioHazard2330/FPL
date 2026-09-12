"""Real walk-forward backtest for team_strength_dc.py's Dixon-Coles fit
(2026-09-12, direct user complaint: "optimizer aint looking that good...
after seeing the wildcard squad it showed i laughed out loud" - the
specific hypothesis under test was that `half_life_days=365.0` reacts too
slowly to a real in-season form collapse, e.g. Marmoush/Spurs' real 0-goal
GW1-3 run). `component_validation.py`'s own module docstring already
claimed clean sheets were "already covered by this project's own existing
team-strength walk-forward work" - that work never actually existed as a
committed, reusable module before this; this closes that gap for real.

Mirrors harness.py's own round-based walk-forward convention (ROUND_SIZE
match-dates per round) rather than a literal FPL gameweek, same reasoning
that module's docstring gives. Scores real predicted (lam, mu) expected
goals against real match_results_history goals via MAE - a fixture-level,
team-vs-team check, deliberately not tied to any one player, since Dixon-
Coles is a TEAM-level model (a player's own share of those goals is a
separate mechanism, models/player_regression.py::player_share_of_team_xg).

Real finding from running this against 2022-23/2023-24/2024-25/2025-26 (4
real completed seasons) the day this module was built: half_life_days=365
(the live default) had the LOWEST real goals MAE of every candidate tried
(240/180/150/120/90), both overall and restricted to each season's first 3
rounds specifically (where a staleness bug would show up most). Shortening
the half-life to "react faster" measurably made real historical accuracy
WORSE, not better, monotonically, at every step down - the opposite of the
original hypothesis. See CLAUDE.md's known-blockers entry for the numbers
and the conclusion this led to (the half-life/ridge-lambda were NOT
changed on this evidence - team-goal accuracy was never actually broken;
Marmoush's specific case traced to a genuine chance-quality-vs-finishing-
variance story, not a stale team rating - see that entry for the detail).
"""
import statistics
from dataclasses import dataclass

from fpl_agent.backtesting.harness import _round_start_dates
from fpl_agent.models.team_strength_dc import _RIDGE_LAMBDA, expected_goals, fit_dixon_coles, load_matches_for_fitting

_MIN_MATCHES_TO_FIT = 20


@dataclass(frozen=True)
class TeamStrengthBacktestResult:
    season: str
    half_life_days: float
    ridge_lambda: float
    rounds_evaluated: int
    goals_scored: int
    goals_mae: float


def score_team_strength(
    conn, season: str, half_life_days: float = 365.0, ridge_lambda: float = _RIDGE_LAMBDA, lookback_days: int = 730,
) -> TeamStrengthBacktestResult:
    """Real walk-forward MAE of Dixon-Coles' own predicted per-team goals
    against actual match goals, refitting once per round from only
    strictly-prior match_results_history rows (identical no-leakage
    discipline as harness.py - as_of_date is always a real ROUND START
    date, never contaminated by that round's own results). Lets a caller
    directly compare candidate half_life_days/ridge_lambda values against
    real historical seasons before ever changing the live default - see
    this module's own docstring for why that discipline matters here
    specifically (a real, counter-intuitive finding already came out of it
    once)."""
    starts = _round_start_dates(conn, season)
    if not starts:
        raise ValueError(f"no match_results_history rows for season {season}")
    boundaries = starts + [None]

    errors: list[float] = []
    rounds_with_predictions = 0
    for i in range(len(starts)):
        round_start, round_end = boundaries[i], boundaries[i + 1]
        matches, team_ids = load_matches_for_fitting(conn, round_start, lookback_days=lookback_days)
        if len(matches) < _MIN_MATCHES_TO_FIT or len(team_ids) < 2:
            continue
        try:
            model = fit_dixon_coles(matches, team_ids, half_life_days=half_life_days, ridge_lambda=ridge_lambda)
        except RuntimeError:
            continue

        clause = "AND match_date < ?" if round_end else ""
        params = (season, round_start) + ((round_end,) if round_end else ())
        rows = conn.execute(
            f"SELECT home_team_id, away_team_id, home_goals, away_goals FROM match_results_history "
            f"WHERE season=? AND match_date >= ? {clause}", params,
        ).fetchall()

        round_scored = False
        for row in rows:
            if row["home_team_id"] not in model.teams or row["away_team_id"] not in model.teams:
                # A real team with no fitted rating yet in this lookback window
                # (e.g. newly promoted, zero prior-season PL matches) - honestly
                # excluded from this round's score, never guessed at.
                continue
            lam, mu = expected_goals(model, row["home_team_id"], row["away_team_id"])
            errors.append(abs(lam - row["home_goals"]))
            errors.append(abs(mu - row["away_goals"]))
            round_scored = True
        if round_scored:
            rounds_with_predictions += 1

    return TeamStrengthBacktestResult(
        season=season, half_life_days=half_life_days, ridge_lambda=ridge_lambda,
        rounds_evaluated=rounds_with_predictions, goals_scored=len(errors),
        goals_mae=round(statistics.mean(errors), 4) if errors else 0.0,
    )
