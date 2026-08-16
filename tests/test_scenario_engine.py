import numpy as np
from types import SimpleNamespace

from fpl_agent.models.scenario_engine import _sample_fixture_scorelines, _sample_player_trial_points


def test_reproducible_with_fixed_seed():
    rng1 = np.random.default_rng(42)
    rng2 = np.random.default_rng(42)
    h1, a1 = _sample_fixture_scorelines(rng1, lam=1.5, mu=1.1, rho=-0.1, n_trials=500)
    h2, a2 = _sample_fixture_scorelines(rng2, lam=1.5, mu=1.1, rho=-0.1, n_trials=500)
    assert np.array_equal(h1, h2)
    assert np.array_equal(a1, a2)


def test_marginal_means_track_lambda_and_mu_at_zero_rho():
    rng = np.random.default_rng(7)
    home, away = _sample_fixture_scorelines(rng, lam=1.8, mu=1.2, rho=0.0, n_trials=50000)
    # 50000 trials at rho=0 (plain Poisson) - sample mean within 0.05 of the true rate
    # is well inside a Poisson(1.8) mean's standard error (~sqrt(1.8/50000)=0.006) at this n.
    assert abs(home.mean() - 1.8) < 0.05
    assert abs(away.mean() - 1.2) < 0.05


def test_negative_rho_increases_scoreless_draws_vs_independent_poisson():
    # Real Dixon-Coles fits typically have rho < 0, which per the tau adjustment
    # (tau(0,0) = 1 - lam*mu*rho) INCREASES P(0,0) relative to independent Poisson -
    # football has more 0-0/1-1 results than independent Poisson predicts. This is
    # the whole reason models/team_strength_dc.py fits rho at all; a sampler that
    # ignored it would silently discard real calibration.
    rng_indep = np.random.default_rng(1)
    rng_correlated = np.random.default_rng(1)
    lam, mu = 1.3, 1.1
    h0, a0 = _sample_fixture_scorelines(rng_indep, lam, mu, rho=0.0, n_trials=100000)
    h1, a1 = _sample_fixture_scorelines(rng_correlated, lam, mu, rho=-0.15, n_trials=100000)
    rate_00_indep = ((h0 == 0) & (a0 == 0)).mean()
    rate_00_correlated = ((h1 == 0) & (a1 == 0)).mean()
    assert rate_00_correlated > rate_00_indep


def _rates(**overrides):
    base = dict(
        position="FWD", goals_rate=4.0, assists_rate=3.0, clean_sheet_pts=0.0,
        shrunk_xa90=0.0, shrunk_cards90=0.0, yellow_card_rate=-1.0,
        player_share_per90=1.0, bonus90=0.0,
        minutes_probs=SimpleNamespace(p_zero=0.0, p_partial=0.0, p_full=1.0),
    )
    base.update(overrides)
    return base


def test_player_always_plays_full_and_scores_every_team_goal():
    # player_share_per90=1.0, p_full=1.0 -> deterministic: every team goal is this
    # player's goal, every trial. team scores exactly 2 every trial (fixed array).
    rng = np.random.default_rng(1)
    team_goals = np.full(1000, 2)
    opp_goals = np.full(1000, 0)
    points = _sample_player_trial_points(rng, _rates(), conceded_rate=0.0, team_goals=team_goals, opp_goals=opp_goals)
    # appearance(2.0) + 2 goals * 4.0 = 10.0, every trial - no randomness left once
    # minutes/goal-share are both deterministic at 1.0.
    assert np.all(points == 10.0)


def test_never_plays_scores_nothing():
    rng = np.random.default_rng(2)
    rates = _rates(minutes_probs=SimpleNamespace(p_zero=1.0, p_partial=0.0, p_full=0.0))
    team_goals = np.full(200, 3)
    opp_goals = np.full(200, 0)
    points = _sample_player_trial_points(rng, rates, conceded_rate=0.0, team_goals=team_goals, opp_goals=opp_goals)
    assert np.all(points == 0.0)


def test_defender_conceded_penalty_scales_with_opponent_goals():
    rng = np.random.default_rng(3)
    rates = _rates(position="DEF", goals_rate=6.0, clean_sheet_pts=4.0, player_share_per90=0.05)
    team_goals = np.zeros(500, dtype=int)
    opp_goals = np.full(500, 4)  # floor(4/2)=2 penalty units every trial, full minutes every trial
    points = _sample_player_trial_points(rng, rates, conceded_rate=-1.0, team_goals=team_goals, opp_goals=opp_goals)
    # appearance 2.0 + 0 clean sheet (opp scored) + (4//2)*-1.0 = 2.0 - 2.0 = 0.0, every trial
    assert np.all(points == 0.0)
