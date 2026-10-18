"""Goalkeeper saves, which the projections did not model at all before
2026-10-18. FPL pays a point per 3 saves, and a goalkeeper makes about 3 a match,
so the omission was about a point a match for every keeper."""
import numpy as np

SAVES_INTERCEPT = 2.01
SAVES_PER_OPP_GOAL = 0.617
SAVES_REFERENCE_GOALS = 1.52


def expected_saves(opp_goals):
    """Saves over a full match, linear in the goals the opponent scores or is
    expected to: 2.01 + 0.617 x (goals - 1.52), fitted to 120 goalkeeper starts
    of 85+ minutes in 2026-27 (FPL's expected goals conceded against saves,
    r = 0.31; mean 2.95 saves at 1.52 xGC). Two parameters from 120 matches: the
    intercept is solid, the slope is not, so it is an approximation to revisit
    as the season adds starts. Accepts a number or an array."""
    return np.maximum(SAVES_INTERCEPT + SAVES_PER_OPP_GOAL * (np.asarray(opp_goals, dtype=float) - SAVES_REFERENCE_GOALS), 0.5)
