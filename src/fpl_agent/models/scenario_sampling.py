"""Pure Monte-Carlo sampling primitives, extracted from scenario_engine.py
(2026-08-21) so expected_points.py can reuse the SAME real per-trial point
model for genuine sampled floor/ceiling bands, without a circular import
(scenario_engine.py itself imports fixture/rates helpers FROM
expected_points.py). No dependency on either module - pure math over
already-computed inputs (lam/mu/rho, a rates dict, drawn scorelines).
"""
import numpy as np
from scipy.stats import poisson

_MAX_GOALS_GRID = 10  # tail probability beyond this is negligible for realistic fixture rates

# Real, disclosed, uncalibrated heuristic (2026-09-13, "make the optimizer
# smarter" research pass, grounded in FPL's own official Bonus Points
# System table - cross-verified live against premierleague.com/livefpl.com:
# a goal is +24 BPS for MID/FWD, +12 for DEF/GKP; an assist is +3 BPS for
# every position - real, large, direct contributors toward being one of a
# match's top-3 BPS scorers, who split the real 3/2/1 bonus points). A
# trial where THIS player actually scored/assisted is mechanically far
# more likely to be a top-3 BPS performer that match than a trial where
# they didn't - a real correlation the bonus draw never modeled before
# this (previously a flat Poisson(bonus90) fully independent of the SAME
# trial's own drawn goals/assists - the exact "sample player_trial_points"
# gap this project's own 2026-08-28 correlation audit disclosed and
# deferred: "a player's OWN bonus should correlate with THEIR OWN trial's
# goals/assists, currently independent"). 2.0x is a directional, bounded
# heuristic, not a fabricated precise number - no source this project has
# carries match-level BPS to calibrate the exact multiplier against (see
# CLAUDE.md's own "Bonus/BPS is season-grain, not match-grain" blocker).
_BONUS_INVOLVEMENT_BOOST = 2.0


def _bonus_correlation_multiplier(involved: np.ndarray) -> np.ndarray:
    """Mean-preserving by construction: `p_involved` is the REALIZED
    empirical involvement rate within this exact trial batch, so the
    batch's own average multiplier is exactly 1.0 (solved algebraically
    below) - the real bonus90 rate this project already computes elsewhere
    is never inflated in aggregate, only redistributed toward the trials
    where a goal/assist actually happened, matching real BPS mechanics
    qualitatively without needing the exact (unpublished, uncalibratable)
    BPS-to-bonus-points conversion."""
    p_involved = involved.mean()
    if not (0.0 < p_involved < 1.0):
        return np.ones_like(involved, dtype=float)
    dampen = max((1.0 - p_involved * _BONUS_INVOLVEMENT_BOOST) / (1.0 - p_involved), 0.0)
    return np.where(involved, _BONUS_INVOLVEMENT_BOOST, dampen)


def sample_fixture_scorelines(
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


def sample_player_trial_points(
    rng: np.random.Generator,
    rates: dict,
    conceded_rate: float,
    team_goals: np.ndarray,
    opp_goals: np.ndarray,
) -> np.ndarray:
    """Vectorized per-trial FPL points for one player in one fixture, given that
    fixture's already-drawn (team_goals, opp_goals). Bonus is a Poisson draw
    correlated with THIS trial's own goals/assists (see
    _bonus_correlation_multiplier); the goals-conceded penalty is a per-trial-
    weighted mean rather than an atomic draw - see
    scenario_engine.py's module docstring for why (no source has real per-trial
    bonus/BPS data to sample a distribution from)."""
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

    # Real joint attribution (2026-09-13, "make the optimizer smarter" pass)
    # - mirrors _match_components' own fixture-aware assists formula exactly
    # (team_goals * assisted_goal_rate * assist_share_per90 * weight *
    # assists_rate, in expectation) and bounds THIS trial's own assist count
    # by that SAME trial's own drawn team_goals - an assist cannot exist
    # without a goal. Closes the real, disclosed "independent assist draws
    # violate the real team-goals ceiling in ~7% of trials" correlation gap
    # (2026-08-28 audit) the same real way the 2026-08-28 goals fix closed
    # the analogous goals-double-counting gap.
    assisted_goals = rng.binomial(team_goals, rates["assisted_goal_rate"])
    assist_prob = np.clip(rates["assist_share_per90"] * weight, 0.0, 1.0)
    assists = rng.binomial(assisted_goals, assist_prob)
    assists_points = assists * rates["assists_rate"]

    card_prob = np.clip(rates["shrunk_cards90"] * weight, 0.0, 1.0)
    card_drawn = rng.random(n_trials) < card_prob
    cards_points = card_drawn.astype(float) * rates["yellow_card_rate"]

    # Poisson-distributed, mean-preserving (E[bonus] = bonus90 * weight, matching the
    # shrinkage-regressed expectation exactly) - see scenario_engine.py's module
    # docstring for why this is the honest approximation available. Real intra-
    # player correlation (2026-09-13) - see _bonus_correlation_multiplier's own
    # docstring - concentrates bonus toward THIS trial's own goal/assist, not
    # just this player's season-average rate independent of what happened here.
    involved = (player_goals + assists) > 0
    bonus_rate = np.clip(rates["bonus90"] * weight, 0.0, None) * _bonus_correlation_multiplier(involved)
    bonus_points = rng.poisson(bonus_rate)

    # A clean sheet is a hard 60-minute threshold, same as _match_components - p_full
    # only, not the blended partial-appearance weight.
    clean_sheet_points = np.where(played_full & (opp_goals == 0), rates["clean_sheet_pts"], 0.0)
    conceded_points = (opp_goals // 2) * conceded_rate * np.minimum(weight, 1.0)

    return appearance + goals_points + assists_points + bonus_points + cards_points + clean_sheet_points + conceded_points


def sample_team_group_trial_points(
    rng: np.random.Generator,
    players: list[dict],
    team_goals: np.ndarray,
    opp_goals: np.ndarray,
) -> dict[int, np.ndarray]:
    """Real correlation fix (2026-08-28, direct user correlation audit:
    "trace whether the simulation correctly handles same-team attackers").
    `sample_player_trial_points` draws each player's own goal count
    independently via `rng.binomial(team_goals, goal_prob)` - correct (and
    left unchanged, see `sample_season_scenarios`) for the common case of
    exactly one squad-tracked scorer per team+fixture, but a real, confirmed
    LOGICAL inconsistency when two+ squad-tracked teammates share a fixture:
    independent per-player draws can double (or triple-)count the same real
    goal - e.g. two Man City attackers each independently drawing 2 goals in
    a trial where the team only scored 2 in total, four individual "goals"
    attributed to a real team total of two. Not merely an understated
    correlation - team_goals is a hard real constraint on how many goals
    exist to attribute in that trial.

    `players`: `[{"player_id", "rates", "conceded_rate"}, ...]` - every
    squad-tracked player sharing this exact team+fixture. Jointly
    multinomial-attributes `team_goals` across the group PLUS an implicit
    "someone else on the team" residual bucket (`1 - sum(shares)`) per
    trial, so the group's own drawn goals can never exceed the real team
    total. Reduces to the existing single-player binomial exactly when
    `len(players) == 1` (a 2-outcome multinomial IS a binomial), so this is
    a strict generalization, not a competing model.

    Cards/clean-sheet/conceded stay independent ACROSS players, same formulas
    `sample_player_trial_points` already uses - there is no real team-
    relative share primitive for those (a card or a clean sheet isn't a
    single shared team resource the way goals/assists are), so a matching
    joint-attribution fix for them isn't a same-scope change. Bonus
    (2026-09-13) is still independent across players but is now correlated
    with THIS SAME player's own drawn goals/assists within the trial - see
    _bonus_correlation_multiplier - a different, real correlation axis
    (intra-player, not cross-player) than the goals/assists one this
    docstring is about.

    Assists (2026-09-13, "make the optimizer smarter" pass) now get the
    SAME real joint multinomial-attribution treatment as goals - closing
    the real, disclosed "independent assist draws violate the real team-
    goals ceiling in ~7% of trials" correlation gap (2026-08-28 audit).
    `player_share_of_team_assists`/`real_assisted_goal_rate` (see
    models/player_regression.py) are the assists counterpart to
    `player_share_of_team_xg` this docstring used to say didn't exist."""
    n_trials = team_goals.shape[0]

    buckets, weights, played_full_list = [], [], []
    for p in players:
        probs = p["rates"]["minutes_probs"]
        bucket = rng.choice(3, size=n_trials, p=[probs.p_zero, probs.p_partial, probs.p_full])
        buckets.append(bucket)
        weights.append(np.where(bucket == 0, 0.0, np.where(bucket == 1, 1 / 3, 1.0)))
        played_full_list.append(bucket == 2)

    # A benched-this-trial player can't score - their own share collapses to 0
    # via `weight`, same as the single-player path already does.
    goal_probs = np.stack(
        [np.clip(p["rates"]["player_share_per90"] * w, 0.0, 1.0) for p, w in zip(players, weights, strict=True)], axis=1
    )  # shape (n_trials, n_players)
    residual = np.clip(1.0 - goal_probs.sum(axis=1, keepdims=True), 0.0, None)
    pvals = np.concatenate([goal_probs, residual], axis=1)
    pvals = pvals / pvals.sum(axis=1, keepdims=True)  # guard float drift before multinomial's own strict-sum check

    drawn = rng.multinomial(team_goals, pvals)  # shape (n_trials, n_players + 1)

    # Real joint assist attribution (2026-09-13) - `assisted_goals` is a real
    # TEAM-level fact (how many of this trial's own team_goals carried a
    # credited assist at all), drawn ONCE and shared across the whole group,
    # mirroring `team_goals` itself - drawing it per-player independently
    # would let the group's own summed assists exceed the team's real
    # assisted-goal count, the exact bug this fix closes. `assisted_goal_rate`
    # is a real global constant (models/player_regression.py::
    # real_assisted_goal_rate), identical on every player's own `rates` dict,
    # so any player's copy is the real, shared value.
    assisted_goal_rate = players[0]["rates"]["assisted_goal_rate"]
    assisted_goals = rng.binomial(team_goals, assisted_goal_rate)
    assist_probs = np.stack(
        [np.clip(p["rates"]["assist_share_per90"] * w, 0.0, 1.0) for p, w in zip(players, weights, strict=True)], axis=1
    )
    assist_residual = np.clip(1.0 - assist_probs.sum(axis=1, keepdims=True), 0.0, None)
    assist_pvals = np.concatenate([assist_probs, assist_residual], axis=1)
    assist_pvals = assist_pvals / assist_pvals.sum(axis=1, keepdims=True)
    assists_drawn_matrix = rng.multinomial(assisted_goals, assist_pvals)  # shape (n_trials, n_players + 1)

    result = {}
    for i, p in enumerate(players):
        rates = p["rates"]
        weight = weights[i]
        played_full = played_full_list[i]
        appearance = np.where(buckets[i] == 0, 0.0, np.where(buckets[i] == 1, 1.0, 2.0))
        goals_points = drawn[:, i] * rates["goals_rate"]

        assists_drawn = assists_drawn_matrix[:, i]
        assists_points = assists_drawn * rates["assists_rate"]

        card_prob = np.clip(rates["shrunk_cards90"] * weight, 0.0, 1.0)
        cards_points = (rng.random(n_trials) < card_prob).astype(float) * rates["yellow_card_rate"]

        # Same real intra-player bonus/goal-assist correlation as
        # sample_player_trial_points - see _bonus_correlation_multiplier.
        involved = (drawn[:, i] + assists_drawn) > 0
        bonus_rate = np.clip(rates["bonus90"] * weight, 0.0, None) * _bonus_correlation_multiplier(involved)
        bonus_points = rng.poisson(bonus_rate)

        clean_sheet_points = np.where(played_full & (opp_goals == 0), rates["clean_sheet_pts"], 0.0)
        conceded_points = (opp_goals // 2) * p["conceded_rate"] * np.minimum(weight, 1.0)

        result[p["player_id"]] = (
            appearance + goals_points + assists_points + bonus_points + cards_points
            + clean_sheet_points + conceded_points
        )
    return result
