"""Scenario-sampling engine (Pillar 1 Plan 1b, spec 2026-08-15-market-rivaling-
architecture-design.md / design doc 2026-08-16-decision-intelligence-plan1b-design.md).

Draws actual scorelines from the Dixon-Coles-fitted Poisson distributions (not their
point estimates), propagates them through the same per-fixture point formula
models/expected_points.py::_match_components already uses for its EXPECTATIONS - but
samples a concrete outcome per trial for each stochastic component instead of averaging.
Both the chip DP scheduler and fpl season-sim consume the same trial draws, so they can
never silently disagree about the same fixture's odds (the reason this module exists as
one shared piece of infrastructure rather than two independent samplers).

Bonus points are NOT sampled per trial - no per-trial bonus distribution exists (same
gap models/expected_points.py::core_expected_points already documents for Pillar 0).
Only the historical-average bonus90 contribution is added, scaled by the trial's own
minutes weight. This means trial totals do not capture bonus-point variance, only its
mean - a known, documented limitation, not a silent gap.

RNG convention: every sampling function here takes an explicit np.random.Generator -
never global numpy random state - so trials are reproducible under a fixed seed. This
is the first RNG usage in the codebase; there is no prior convention to match.
"""

import sqlite3
from dataclasses import dataclass

import numpy as np
from scipy.stats import poisson

_MAX_GOALS_GRID = 10  # tail probability beyond this is negligible for realistic fixture rates


def _sample_fixture_scorelines(
    rng: np.random.Generator, lam: float, mu: float, rho: float, n_trials: int, max_goals: int = _MAX_GOALS_GRID
) -> tuple[np.ndarray, np.ndarray]:
    """Dixon-Coles-correlated scoreline draws for one fixture. Builds the full joint
    probability grid over a bounded (max_goals+1)x(max_goals+1) score space, applies the
    same low-score tau adjustment the DC fit's own likelihood uses (models/team_strength_dc.py's
    `rho`) to the (0,0)/(1,0)/(0,1)/(1,1) cells, renormalizes, then draws via one vectorized
    categorical sample - not independent per-side Poisson draws, which would drop the
    correlation the fit was calibrated with."""
    x = np.arange(max_goals + 1)
    home_pmf = poisson.pmf(x, lam)
    away_pmf = poisson.pmf(x, mu)
    joint = np.outer(home_pmf, away_pmf)  # joint[h, a]

    tau = np.ones_like(joint)
    tau[0, 0] = 1 - lam * mu * rho
    tau[0, 1] = 1 + lam * rho
    tau[1, 0] = 1 + mu * rho
    tau[1, 1] = 1 - rho
    joint = np.clip(joint * tau, 0, None)  # guard against a pathological rho driving a cell negative
    joint = joint / joint.sum()

    flat_index = rng.choice(joint.size, size=n_trials, p=joint.ravel())
    home_goals, away_goals = np.unravel_index(flat_index, joint.shape)
    return home_goals, away_goals


def _sample_player_trial_points(
    rng: np.random.Generator,
    rates: dict,
    conceded_rate: float,
    team_goals: np.ndarray,
    opp_goals: np.ndarray,
) -> np.ndarray:
    """Vectorized per-trial FPL points for one player in one fixture, given that
    fixture's already-drawn (team_goals, opp_goals) - see module docstring for which
    terms are sampled vs kept as a deterministic expectation (bonus)."""
    n_trials = team_goals.shape[0]
    probs = rates["minutes_probs"]
    bucket = rng.choice(3, size=n_trials, p=[probs.p_zero, probs.p_partial, probs.p_full])  # 0=none,1=partial,2=full
    appearance = np.where(bucket == 0, 0.0, np.where(bucket == 1, 1.0, 2.0))
    # Mirrors _match_components' effective_minutes_fraction blend (p_partial/3 + p_full)
    # translated from an aggregate expectation into a per-trial indicator weight.
    weight = np.where(bucket == 0, 0.0, np.where(bucket == 1, 1 / 3, 1.0))
    played_full = bucket == 2

    goal_prob = np.clip(rates["player_share_per90"] * weight, 0.0, 1.0)
    player_goals = rng.binomial(team_goals, goal_prob)
    goals_points = player_goals * rates["goals_rate"]

    assist_rate = np.clip(rates["shrunk_xa90"] * weight, 0.0, None)
    assists = rng.poisson(assist_rate)
    assists_points = assists * rates["assists_rate"]

    card_prob = np.clip(rates["shrunk_cards90"] * weight, 0.0, 1.0)
    card_drawn = rng.random(n_trials) < card_prob
    cards_points = card_drawn.astype(float) * rates["yellow_card_rate"]

    bonus_points = rates["bonus90"] * weight  # deterministic - see module docstring

    # A clean sheet is a hard 60-minute threshold, same as _match_components - p_full
    # only, not the blended partial-appearance weight.
    clean_sheet_points = np.where(played_full & (opp_goals == 0), rates["clean_sheet_pts"], 0.0)
    conceded_points = (opp_goals // 2) * conceded_rate * np.minimum(weight, 1.0)

    return appearance + goals_points + assists_points + bonus_points + cards_points + clean_sheet_points + conceded_points
