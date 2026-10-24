"""HOW SURE IS A TRANSFER - a move priced as a bet, not a number.

The week plan prices a move by expected points over the horizon, and a move
clears when it adds 1.5. Expected value hides how thin that can be: +2.2 points
over five gameweeks is a small edge against the spread of two players' scores,
and a manager who sees a player drifting is reading a risk the point estimate
does not show. This replays the moves 4,000 times with the scenario engine (one
scoreline per fixture shared by both teams, so teammates and opponents are
correlated as they are in a match) and reports how often the player coming in
outscores the one going out over the horizon.

Two sources of spread are in it:
- match randomness: the scenario engine's own draws;
- talent uncertainty: each trial multiplies a player's horizon points by one
  lognormal factor, with sigma = 1 / sqrt(effective xG + xA events behind his
  rate: his season total plus three), clipped to 0.15-0.45. A player with 3.6 xG
  and 1.2 xA has sigma 0.34 around his own rate: the model's estimate of him is
  uncertain by about a third, which a fixed rate hides. The factor is applied to
  all of his points, appearance points included, which slightly overstates
  variance for a player on minutes alone; it is shared across the horizon because
  it is one unknown rate, not one per match.

The simulation's mean difference is not the planner's gain (the planner uses its
own horizon projections); the two are shown side by side and the probability is
the simulation's.
"""
import sqlite3

import numpy as np

from fpl_agent.models.scenario_engine import sample_season_arrays

N_TRIALS = 4000
SEED = 20261021
SIGMA_MIN, SIGMA_MAX = 0.15, 0.45
PRIOR_EVENTS = 3.0


def talent_sigma(conn: sqlite3.Connection, player_id: int) -> float:
    row = conn.execute(
        "SELECT expected_goals, expected_assists FROM player_stats_snapshot WHERE player_id = ? ORDER BY retrieved_at DESC LIMIT 1", (player_id,)
    ).fetchone()
    events = float(row["expected_goals"] or 0) + float(row["expected_assists"] or 0) if row else 0.0
    return float(min(max(1.0 / np.sqrt(events + PRIOR_EVENTS), SIGMA_MIN), SIGMA_MAX))


def move_confidence(conn: sqlite3.Connection, pairs: list[tuple[int, int]], event: int, horizon: int, n_trials: int = N_TRIALS) -> dict[tuple[int, int], dict]:
    if not pairs:
        return {}
    ids = sorted({p for pair in pairs for p in pair})
    rng = np.random.default_rng(SEED)
    arrays = sample_season_arrays(conn, ids, event, horizon, n_trials, rng)
    totals = {pid: np.zeros(n_trials) for pid in ids}
    for (_ev, pid), arr in arrays.items():
        totals[pid] = totals[pid] + arr
    sigma = {pid: talent_sigma(conn, pid) for pid in ids}
    factor = {pid: np.exp(rng.normal(-0.5 * sigma[pid] ** 2, sigma[pid], n_trials)) for pid in ids}
    adjusted = {pid: totals[pid] * factor[pid] for pid in ids}
    out: dict[tuple[int, int], dict] = {}
    for out_id, in_id in pairs:
        diff = adjusted[in_id] - adjusted[out_id]
        out[(out_id, in_id)] = {
            "win_prob": round(float((diff > 0).mean()), 3), "mean_diff": round(float(diff.mean()), 2), "sd_diff": round(float(diff.std()), 2),
            "p10": round(float(np.percentile(diff, 10)), 1), "p90": round(float(np.percentile(diff, 90)), 1),
            "sigma_in": round(sigma[in_id], 2), "sigma_out": round(sigma[out_id], 2), "trials": n_trials, "horizon": horizon,
        }
    return out


def verdict(win_prob: float) -> str:
    return "SOLID" if win_prob >= 0.65 else "LEAN" if win_prob >= 0.55 else "THIN"
