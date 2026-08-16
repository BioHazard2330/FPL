import numpy as np

from fpl_agent.models.scenario_engine import _sample_fixture_scorelines


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
