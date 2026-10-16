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


def test_ridge_shrinks_a_one_match_shock_result_toward_average():
    """Real regression test for a confirmed live bug (2026-08-28): a
    newly-promoted team's real GW1 shock win (Hull 2-0 Man Utd, 2026-27)
    fit with zero regularization ran attack/defence to the edge of the
    optimizer's own +-3 bound off that single match, producing an
    implausible 83% clean-sheet projection three gameweeks later against an
    unrelated opponent. Team 4 here plays exactly one match (a big away win,
    the same real shape as Hull's shock result) while teams 1-3 have many -
    with the default ridge, team 4's defence must land far short of the
    bound a real shock result alone would otherwise drive it to."""
    many_matches = [
        Match(home_team_id=1, away_team_id=2, home_goals=1, away_goals=1, days_since=d)
        for d in range(10, 200, 10)
    ] + [
        Match(home_team_id=2, away_team_id=3, home_goals=1, away_goals=1, days_since=d)
        for d in range(15, 200, 10)
    ] + [
        Match(home_team_id=3, away_team_id=1, home_goals=1, away_goals=1, days_since=d)
        for d in range(20, 200, 10)
    ]
    shock_match = [Match(home_team_id=4, away_team_id=1, home_goals=2, away_goals=0, days_since=5)]
    matches = many_matches + shock_match
    team_ids = [4, 1, 2, 3]  # team 4 (the sparse one) must NOT be team_ids[-1] - that slot is the fixed attack=defence=0 reference

    regularized = fit_dixon_coles(matches, team_ids, half_life_days=365.0)
    unregularized = fit_dixon_coles(matches, team_ids, half_life_days=365.0, ridge_lambda=0.0)

    # The unregularized fit really does run to (near) the bound on one shock
    # match alone - confirms this test would have caught the real bug.
    assert unregularized.teams[4].defence <= -2.0

    # The default-ridge fit pulls the same team's defence much closer to 0
    # (league-average) - the real fix, not just a tighter optimizer bound.
    assert regularized.teams[4].defence > -1.0


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

    nll_a = team_strength_dc._neg_log_likelihood(params_a, team_ids, matches, decay_k=0.0, ridge_lambda=0.0)
    nll_b = team_strength_dc._neg_log_likelihood(params_b, team_ids, matches, decay_k=0.0, ridge_lambda=0.0)

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


def _market_team(conn, name):
    cur = conn.execute("INSERT INTO market_teams (canonical_name) VALUES (?)", (name,))
    return cur.lastrowid


def test_loader_attaches_team_xg_and_falls_back_to_goals(db_conn):
    from fpl_agent.models.team_strength_dc import load_matches_for_fitting

    a, b = _market_team(db_conn, "A"), _market_team(db_conn, "B")
    for date, hg, ag in (("2026-01-10", 0, 1), ("2026-01-20", 2, 2)):
        db_conn.execute(
            "INSERT INTO match_results_history (season, match_date, home_team_id, away_team_id, home_goals, away_goals, source, retrieved_at) "
            "VALUES ('2025-26', ?, ?, ?, ?, ?, 'test', 't')", (date, a, b, hg, ag),
        )
    for team, xg in ((a, 0.7), (a, 0.8), (b, 0.6)):
        db_conn.execute(
            "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, market_team_id, season, match_date, minutes, "
            "goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
            "VALUES ('m1', ?, ?, '2025-26', '2026-01-10', 90, 0, 0, 1, ?, 0, 0, 0, 0, 't')", (f"p{team}{xg}", team, xg),
        )
    db_conn.commit()

    matches, _ = load_matches_for_fitting(db_conn, "2026-02-01")
    first, second = matches
    assert first.home_xg == pytest.approx(1.5) and first.away_xg == pytest.approx(0.6)
    assert second.home_xg is None and second.away_xg is None


def test_a_team_that_created_chances_without_scoring_is_not_rated_like_one_that_created_none():
    from fpl_agent.models.team_strength_dc import fit_dixon_coles

    def season(xg_for_team_one):
        out = []
        for d in range(10, 300, 20):
            out.append(Match(1, 2, 0, 0, d, xg_for_team_one, 0.4))
            out.append(Match(2, 1, 1, 0, d + 10, 0.4, xg_for_team_one))
            out.append(Match(1, 3, 0, 1, d + 5, xg_for_team_one, 0.5))
            out.append(Match(3, 1, 1, 0, d + 15, 0.5, xg_for_team_one))
            out.append(Match(2, 3, 1, 1, d + 7, 0.9, 0.9))
        return out

    creating = fit_dixon_coles(season(2.0), [1, 2, 3])
    blank = fit_dixon_coles(season(0.2), [1, 2, 3])
    assert creating.teams[1].attack > blank.teams[1].attack


def test_goals_weight_one_ignores_xg():
    from fpl_agent.models.team_strength_dc import fit_dixon_coles

    with_xg = [Match(1, 2, 1, 0, d, 3.0, 0.1) for d in range(10, 100, 10)] + [Match(2, 1, 0, 1, d + 5, 0.1, 3.0) for d in range(10, 100, 10)]
    without = [Match(1, 2, 1, 0, d) for d in range(10, 100, 10)] + [Match(2, 1, 0, 1, d + 5) for d in range(10, 100, 10)]
    a = fit_dixon_coles(with_xg, [1, 2], goals_weight=1.0)
    b = fit_dixon_coles(without, [1, 2], goals_weight=1.0)
    assert a.teams[1].attack == pytest.approx(b.teams[1].attack, abs=1e-6)
