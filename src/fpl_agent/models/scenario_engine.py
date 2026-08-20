"""Scenario-sampling engine (Pillar 1 Plan 1b, spec 2026-08-15-market-rivaling-
architecture-design.md / design doc 2026-08-16-decision-intelligence-plan1b-design.md).

Draws actual scorelines from the Dixon-Coles-fitted Poisson distributions (not their
point estimates), propagates them through the same per-fixture point formula
models/expected_points.py::_match_components already uses for its EXPECTATIONS - but
samples a concrete outcome per trial for each stochastic component instead of averaging.
"Concrete outcome" is exact for the discrete terms (appearance bucket, goals, assists,
cards, clean sheet); bonus and the goals-conceded penalty are still expectations scaled by
the trial's fractional minutes `weight`, so those two are per-trial-weighted means rather
than literally atomic draws.
Both the chip DP scheduler and fpl season-sim consume the same trial draws, so they can
never silently disagree about the same fixture's odds (the reason this module exists as
one shared piece of infrastructure rather than two independent samplers).

Bonus points ARE sampled per trial (closed 2026-08-20 - see CLAUDE.md's now-closed
"scenario engine doesn't model bonus-point variance" limitation): no source this
project has carries real match-level bonus/BPS award data (BPS is FPL-proprietary,
Understat doesn't have it - the same reason bonus_regression.py's own shrinkage is
season-grain, not match-grain), so there is no real per-trial bonus DISTRIBUTION to
draw from. Real FPL bonus is a discrete {0,1,2,3} award to a match's top-3 BPS
performers - a Poisson draw is the same honest, mean-preserving discrete-count
approximation already used here for assists (also a low-count stat with no per-trial
distribution source), not a perfect model of the real top-3 mechanism. Its mean
still equals models/bonus_regression.py's shrinkage-regressed expected_bonus_per90,
scaled by the trial's own minutes weight - the calibrated mean is unchanged, only
real variance around it is now added.

RNG convention: every sampling function here takes an explicit np.random.Generator -
never global numpy random state - so trials are reproducible under a fixed seed. This
is the first RNG usage in the codebase; there is no prior convention to match.
"""

import sqlite3
from dataclasses import dataclass

import numpy as np
from scipy.stats import poisson

from fpl_agent.models.expected_points import _blended_fixture_goals, _fixture_date, _get_or_fit_dc_model, _player_match_rates
from fpl_agent.models.rules import current_season, get_rule

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

    # Poisson-distributed, mean-preserving (E[bonus] = bonus90 * weight, matching the
    # shrinkage-regressed expectation exactly) - see module docstring for why this is
    # the honest approximation available, not a perfect top-3-BPS model.
    bonus_rate = np.clip(rates["bonus90"] * weight, 0.0, None)
    bonus_points = rng.poisson(bonus_rate)

    # A clean sheet is a hard 60-minute threshold, same as _match_components - p_full
    # only, not the blended partial-appearance weight.
    clean_sheet_points = np.where(played_full & (opp_goals == 0), rates["clean_sheet_pts"], 0.0)
    conceded_points = (opp_goals // 2) * conceded_rate * np.minimum(weight, 1.0)

    return appearance + goals_points + assists_points + bonus_points + cards_points + clean_sheet_points + conceded_points


@dataclass(frozen=True)
class ScenarioOutcome:
    trial_index: int
    points_by_event_player: dict[tuple[int, int], float]


def _draw_fixture_for_team(
    conn: sqlite3.Connection, rng: np.random.Generator, fixture_row, team_id: int, n_trials: int,
    fixture_cache: dict[int, tuple[int, np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    """(team_goals, opp_goals) trial arrays for `team_id` in this fixture. The
    underlying (home_goals, away_goals) draw is cached per fixture_id and reused for
    every player in the match (both teams) - a fixture is drawn once, not once per
    player, so opposing players correctly see the same realized scoreline each trial."""
    fixture_id = fixture_row["id"]
    if fixture_id not in fixture_cache:
        fixture_date = _fixture_date(fixture_row)
        lam, mu = _blended_fixture_goals(conn, fixture_id, fixture_row["team_h"], fixture_row["team_a"], fixture_date)
        dc_model = _get_or_fit_dc_model(conn, fixture_date)
        rho = dc_model.rho if dc_model is not None else 0.0
        home_goals, away_goals = _sample_fixture_scorelines(rng, lam, mu, rho, n_trials)
        fixture_cache[fixture_id] = (fixture_row["team_h"], home_goals, away_goals)
    home_team_id, home_goals, away_goals = fixture_cache[fixture_id]
    return (home_goals, away_goals) if team_id == home_team_id else (away_goals, home_goals)


def sample_season_scenarios(
    conn: sqlite3.Connection,
    squad_ids: list[int],
    from_event: int,
    horizon_gw: int,
    n_trials: int = 1000,
    rng: np.random.Generator | None = None,
) -> list[ScenarioOutcome]:
    rng = rng if rng is not None else np.random.default_rng()
    season = current_season(conn)
    fixture_cache: dict[int, tuple[int, np.ndarray, np.ndarray]] = {}
    per_player_event_trials: dict[tuple[int, int], np.ndarray] = {}

    for player_id in squad_ids:
        team_id = conn.execute("SELECT team_id FROM players WHERE id=?", (player_id,)).fetchone()["team_id"]
        rates = _player_match_rates(conn, player_id, season=season)
        conceded_rate = get_rule(conn, rates["rules_season"], f"scoring.goals_conceded.{rates['position']}", 0) or 0
        if rates["position"] not in ("DEF", "GKP"):
            conceded_rate = 0

        for event in range(from_event, from_event + horizon_gw):
            fixture_rows = conn.execute(
                "SELECT id, team_h, team_a, kickoff_time FROM fixtures WHERE (team_h=? OR team_a=?) AND event=?",
                (team_id, team_id, event),
            ).fetchall()
            total = np.zeros(n_trials)
            for fx in fixture_rows:  # naturally 0 rows (blank) or 2+ rows (double) - no special-casing needed
                team_goals, opp_goals = _draw_fixture_for_team(conn, rng, fx, team_id, n_trials, fixture_cache)
                total = total + _sample_player_trial_points(rng, rates, conceded_rate, team_goals, opp_goals)
            per_player_event_trials[(event, player_id)] = total

    return [
        ScenarioOutcome(trial_index=i, points_by_event_player={k: float(v[i]) for k, v in per_player_event_trials.items()})
        for i in range(n_trials)
    ]
