"""Dixon-Coles bivariate Poisson team-strength model (Dixon & Coles, 1997).
Fits attack/defence ratings per team from historical match goals, with
exponential time-decay weighting toward recent matches and the low-score
correlation (rho) adjustment plain independent-Poisson misses (it
underestimates how often 0-0/1-0/0-1/1-1 actually happen).

The last team in `team_ids` is fixed at attack=defence=0 as the identifiability
reference - standard practice for this model (attack/defence are only
meaningful relative to each other), not a modelling weakness.
"""
import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize


@dataclass(frozen=True)
class Match:
    home_team_id: int
    away_team_id: int
    home_goals: int
    away_goals: int
    days_since: int  # days between this match and the "as of" fitting date


@dataclass(frozen=True)
class TeamStrength:
    market_team_id: int
    attack: float
    defence: float


@dataclass(frozen=True)
class DixonColesModel:
    teams: dict[int, TeamStrength]
    home_advantage: float
    rho: float
    reference_team_id: int


def _tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    if x == 0 and y == 0:
        return 1 - lam * mu * rho
    if x == 0 and y == 1:
        return 1 + lam * rho
    if x == 1 and y == 0:
        return 1 + mu * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


_RIDGE_LAMBDA = 2.5  # real, disclosed shrinkage strength - see fit_dixon_coles's own docstring for why


def _neg_log_likelihood(params, team_ids, matches, decay_k, ridge_lambda):
    n = len(team_ids)
    attack = dict(zip(team_ids[:-1], params[: n - 1]))
    defence = dict(zip(team_ids[:-1], params[n - 1 : 2 * (n - 1)]))
    attack[team_ids[-1]] = 0.0
    defence[team_ids[-1]] = 0.0
    gamma, rho = params[-2], params[-1]

    total = 0.0
    weight_sum = 0.0
    for m in matches:
        lam = math.exp(attack[m.home_team_id] + defence[m.away_team_id] + gamma)
        mu = math.exp(attack[m.away_team_id] + defence[m.home_team_id])
        weight = math.exp(-decay_k * m.days_since)
        weight_sum += weight
        log_p = (
            -lam + m.home_goals * math.log(lam) - math.lgamma(m.home_goals + 1)
            - mu + m.away_goals * math.log(mu) - math.lgamma(m.away_goals + 1)
        )
        # NOTE: tau(x, y) is only defined (non-1) for the exact scorelines
        # (0,0)/(1,0)/(0,1)/(1,1) per Dixon & Coles (1997) eq. 4 - it corrects
        # for the observed excess/deficit of those specific low-score results
        # relative to independent Poisson. Passing the *actual* goal counts
        # (not capped to {0,1}) is required: capping would misapply the
        # adjustment to unrelated scorelines such as 3-0 or 2-1, which the
        # catch-all `return 1.0` branch above is precisely there to exclude.
        tau = max(_tau(m.home_goals, m.away_goals, lam, mu, rho), 1e-10)
        total -= weight * (log_p + math.log(tau))
    # Real L2 (ridge) prior pulling every team's attack/defence toward 0 =
    # league-average (2026-08-28, direct fix for a confirmed real bug: a
    # newly-promoted team with a single real PL match - e.g. Hull's shock
    # 2-0 win over Man Utd in GW1 2026-27 - had an UNREGULARIZED MLE fit run
    # to the edge of the +-3 bound on that one match alone, producing a real
    # 83% clean-sheet projection for Hull three gameweeks later against an
    # unrelated opponent - not plausible for any team, let alone a newly
    # promoted one. A team with many real matches has enough likelihood
    # signal to overcome this fixed penalty and settle near its true rating
    # (same effect a Bayesian MAP prior has); a team with one or two matches
    # does not, and gets pulled back toward average - the same empirical-
    # Bayes shrinkage philosophy this project already applies to every
    # player-level rate (player_regression.py), just missing at the team
    # level until now. `_RIDGE_LAMBDA=2.5` is a disclosed, not-yet-backtest-
    # tuned starting value (this project's own backtest harness scores
    # match-level MAE/RMSE - `fpl backtest` - and should be used to tune
    # this properly once enough of the season has real results to backtest
    # against; picking it by "does Hull's number become plausible again" is
    # a real sanity check, not a substitute for that).
    #
    # Scaled by the MEAN per-match decay weight (not a flat constant) so
    # `_dc_fit_as_of_date`'s own coarsening proof still holds exactly: a
    # uniform shift of every match's `days_since` (fitting the same real
    # historical matches at a different genuinely-future as_of_date)
    # rescales every weight - and therefore this mean - by the identical
    # positive constant `c` the likelihood sum itself is rescaled by, so
    # the WHOLE objective scales by `c` and the argmax is unchanged (a flat,
    # unscaled ridge term would NOT have this property - confirmed by a real
    # test failure during development, `test_dc_fit_coarsening_produces_
    # mathematically_identical_model_params`, which pinned exactly this).
    mean_weight = weight_sum / len(matches)
    total += 0.5 * ridge_lambda * mean_weight * sum(a * a for a in attack.values())
    total += 0.5 * ridge_lambda * mean_weight * sum(d * d for d in defence.values())
    return total


def fit_dixon_coles(
    matches: list[Match], team_ids: list[int], half_life_days: float = 365.0, ridge_lambda: float = _RIDGE_LAMBDA,
) -> DixonColesModel:
    if len(team_ids) < 2:
        raise ValueError("need at least 2 teams to fit Dixon-Coles")
    if not matches:
        raise ValueError("need at least 1 match to fit Dixon-Coles")

    n = len(team_ids)
    decay_k = math.log(2) / half_life_days if half_life_days else 0.0
    x0 = np.zeros(2 * (n - 1) + 2)
    x0[-2] = 0.2  # home-advantage starting guess

    result = minimize(
        _neg_log_likelihood, x0, args=(team_ids, matches, decay_k, ridge_lambda), method="L-BFGS-B",
        bounds=[(-3, 3)] * (2 * (n - 1)) + [(-1, 1), (-0.2, 0.2)],
    )
    if not result.success:
        raise RuntimeError(f"Dixon-Coles fit did not converge: {result.message}")
    params = result.x

    attack = dict(zip(team_ids[:-1], params[: n - 1]))
    defence = dict(zip(team_ids[:-1], params[n - 1 : 2 * (n - 1)]))
    attack[team_ids[-1]] = 0.0
    defence[team_ids[-1]] = 0.0

    teams = {tid: TeamStrength(tid, attack[tid], defence[tid]) for tid in team_ids}
    return DixonColesModel(teams=teams, home_advantage=params[-2], rho=params[-1], reference_team_id=team_ids[-1])


def expected_goals(model: DixonColesModel, home_team_id: int, away_team_id: int) -> tuple[float, float]:
    home, away = model.teams[home_team_id], model.teams[away_team_id]
    lam = math.exp(home.attack + away.defence + model.home_advantage)
    mu = math.exp(away.attack + home.defence)
    return lam, mu


def load_matches_for_fitting(conn, as_of_date: str, lookback_days: int = 730) -> tuple[list[Match], list[int]]:
    rows = conn.execute(
        "SELECT home_team_id, away_team_id, home_goals, away_goals, "
        "CAST(julianday(?) - julianday(match_date) AS INTEGER) AS days_since "
        "FROM match_results_history "
        "WHERE match_date < ? AND julianday(?) - julianday(match_date) <= ? "
        "ORDER BY match_date",
        (as_of_date, as_of_date, as_of_date, lookback_days),
    ).fetchall()
    matches = [
        Match(r["home_team_id"], r["away_team_id"], r["home_goals"], r["away_goals"], r["days_since"])
        for r in rows
    ]
    team_ids = sorted({m.home_team_id for m in matches} | {m.away_team_id for m in matches})
    return matches, team_ids
