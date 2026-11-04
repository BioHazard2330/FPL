import numpy as np

from fpl_agent.models import supercomputer as sc


def _league(points, home=(), away=(), lam=(), mu=()):
    n = len(points)
    return sc.League(list(range(1, n + 1)), np.array(points, float), np.zeros(n), np.zeros(n), np.array(home, dtype=int), np.array(away, dtype=int), np.array(lam, float), np.array(mu, float))


def test_a_finished_season_stands_as_it_is():
    r = sc.simulate_table(_league([10, 30, 20]), 200, 0.0)
    assert list(r["counts"][1]) == [200, 0, 0] and list(r["counts"][2]) == [0, 200, 0] and list(r["counts"][0]) == [0, 0, 200]


def test_every_position_is_filled_in_every_season():
    r = sc.simulate_table(_league([0, 0, 0, 0], (0, 1), (2, 3), (1.4, 1.4), (1.1, 1.1)), 500, 0.2)
    assert (r["counts"].sum(axis=0) == 500).all() and (r["counts"].sum(axis=1) == 500).all()


def test_a_stronger_side_wins_more_and_points_add_up():
    r = sc.simulate_table(_league([0, 0], (0, 0, 0, 0), (1, 1, 1, 1), (3.0, 3.0, 3.0, 3.0), (0.5, 0.5, 0.5, 0.5)), 2000, 0.0)
    assert r["counts"][0, 0] > 1900
    assert 2 * 4 <= r["points"].sum(axis=1).min() and r["points"].sum(axis=1).max() <= 3 * 4


def test_a_lasting_shock_widens_a_clubs_range():
    league = _league([0, 0, 0, 0], (0, 1) * 15, (2, 3) * 15, (1.4,) * 30, (1.1,) * 30)
    flat = sc.simulate_table(league, 3000, 0.0)["points"][:, 0].std()
    shocked = sc.simulate_table(league, 3000, 0.3)["points"][:, 0].std()
    assert shocked > flat * 1.1
