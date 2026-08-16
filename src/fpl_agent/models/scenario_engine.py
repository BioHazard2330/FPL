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
