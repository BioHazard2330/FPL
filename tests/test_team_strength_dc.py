import numpy as np
import pytest

from fpl_agent.models import team_strength_dc
from fpl_agent.models.team_strength_dc import Match, _tau, expected_goals, fit_dixon_coles


def test_fit_dixon_coles_ranks_dominant_team_higher():
    # Team 1 beats team 2 heavily and repeatedly; team 3 is a mid-table draw-machine.
    matches = [
        Match(home_team_id=1, away_team_id=2, home_goals=3, away_goals=0, days_since=10),
        Match(home_team_id=2, away_team_id=1, home_goals=0, away_goals=3, days_since=20),
        Match(home_team_id=1, away_team_id=3, home_goals=2, away_goals=1, days_since=30),
        Match(home_team_id=3, away_team_id=1, home_goals=1, away_goals=2, days_since=40),
        Match(home_team_id=2, away_team_id=3, home_goals=1, away_goals=1, days_since=50),
        Match(home_team_id=3, away_team_id=2, home_goals=1, away_goals=1, days_since=60),
    ]
    model = fit_dixon_coles(matches, team_ids=[1, 2, 3], half_life_days=365.0)

    assert model.teams[1].attack > model.teams[2].attack
    assert model.teams[1].defence < model.teams[2].defence  # lower defence param = concedes less

    lam, mu = expected_goals(model, home_team_id=1, away_team_id=2)
    assert lam > mu  # team 1 expected to outscore team 2 even accounting for home/away


def test_fit_dixon_coles_requires_matches_and_teams():
    with pytest.raises(ValueError):
        fit_dixon_coles([], team_ids=[1, 2])
    with pytest.raises(ValueError):
        fit_dixon_coles([Match(1, 2, 1, 0, 0)], team_ids=[1])


def test_tau_only_adjusts_the_four_low_score_cells():
    # Pins _tau's own contract: it must only special-case the four sparse
    # low-score cells and return exactly 1.0 for everything else - including
    # scorelines that a capped call (`min(x,1)`) would collide with, like
    # (3,0) and (2,1) which would otherwise land on the (1,0)/(1,1) cells.
    assert _tau(3, 0, 2.8, 0.4, -0.2) == 1.0
    assert _tau(2, 1, 2.8, 0.4, -0.2) == 1.0
    assert _tau(0, 0, 2.8, 0.4, -0.2) != 1.0
    assert _tau(0, 1, 2.8, 0.4, -0.2) != 1.0
    assert _tau(1, 0, 2.8, 0.4, -0.2) != 1.0
    assert _tau(1, 1, 2.8, 0.4, -0.2) != 1.0


def test_neg_log_likelihood_ignores_rho_for_non_special_scorelines():
    # Call-site regression pin, complementary to the _tau unit test above:
    # _tau alone can't catch a bug reintroduced at the *call site* in
    # _neg_log_likelihood (e.g. `_tau(min(m.home_goals, 1), min(m.away_goals, 1), ...)`),
    # since _tau's own implementation would be untouched by that. A (3, 0)
    # scoreline isn't one of the four Dixon-Coles low-score cells, so its
    # tau must be 1.0 regardless of rho - meaning the likelihood for this
    # match should be invariant to rho. If the capping bug is reintroduced,
    # (3, 0) gets misrouted to the (1, 0) cell (tau = 1 + mu*rho), which
    # *does* depend on rho, and this test starts failing.
    matches = [Match(home_team_id=1, away_team_id=2, home_goals=3, away_goals=0, days_since=0)]
    team_ids = [1, 2]
    # params layout for 2 teams: [attack[1], defence[1], gamma, rho]
    params_a = np.array([0.1, -0.1, 0.2, -0.15])
    params_b = np.array([0.1, -0.1, 0.2, 0.15])

    nll_a = team_strength_dc._neg_log_likelihood(params_a, team_ids, matches, decay_k=0.0)
    nll_b = team_strength_dc._neg_log_likelihood(params_b, team_ids, matches, decay_k=0.0)

    assert nll_a == pytest.approx(nll_b)


def test_fit_dixon_coles_raises_on_non_convergence(monkeypatch):
    class _FakeResult:
        success = False
        message = "ABNORMAL_TERMINATION_IN_LNSRCH"
        x = np.zeros(1)

    monkeypatch.setattr(team_strength_dc, "minimize", lambda *a, **k: _FakeResult())

    matches = [Match(home_team_id=1, away_team_id=2, home_goals=1, away_goals=0, days_since=1)]
    with pytest.raises(RuntimeError, match="did not converge"):
        fit_dixon_coles(matches, team_ids=[1, 2])
