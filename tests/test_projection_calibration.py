import numpy as np
import pytest

from fpl_agent.models.player_regression import fpl_assist_position_factors, fpl_assisted_goal_rate
from fpl_agent.models.saves import expected_saves
from fpl_agent.models import scenario_sampling as ss


def test_expected_saves_rise_with_the_goals_the_opponent_is_expected_to_score():
    assert float(expected_saves(1.52)) == pytest.approx(2.01)
    assert float(expected_saves(2.5)) > float(expected_saves(1.0))
    assert float(expected_saves(0.0)) >= 0.5
    assert expected_saves(np.array([0.5, 2.0])).shape == (2,)


def test_fpl_assist_credit_falls_back_to_the_measured_rates_without_stored_totals(db_conn):
    assert fpl_assisted_goal_rate(db_conn) == pytest.approx(0.90)
    factors = fpl_assist_position_factors(db_conn)
    assert factors["FWD"] > 1.5 > 1.0 > factors["MID"] > factors["DEF"] > 0.8


def _rates(**kw):
    class P:
        p_zero, p_partial, p_full = 0.0, 0.0, 1.0

    base = {"minutes_probs": P(), "position": "GKP", "defcon_actions90": 0.0}
    base.update(kw)
    return base


def test_goalkeeper_save_points_are_drawn_around_the_match_s_own_opponent_goals():
    rng = np.random.default_rng(3)
    n = 4000
    full = np.ones(n)
    quiet = ss._saves_and_defcon_points(rng, _rates(saves_pts_rule=1), np.zeros(n, dtype=int), full, full > 0)
    busy = ss._saves_and_defcon_points(rng, _rates(saves_pts_rule=1), np.full(n, 4), full, full > 0)
    assert quiet.mean() < 0.2
    assert busy.mean() > 0.5
    none = ss._saves_and_defcon_points(rng, _rates(), np.full(n, 4), full, full > 0)
    assert none.sum() == 0


def test_defensive_contribution_points_need_a_full_match_and_the_rule():
    rng = np.random.default_rng(4)
    n = 4000
    opp = np.zeros(n, dtype=int)
    rates = _rates(position="DEF", defcon_actions90=14.0, defcon_pts_rule=2)
    played = ss._saves_and_defcon_points(rng, rates, opp, np.ones(n), np.ones(n, dtype=bool))
    benched = ss._saves_and_defcon_points(rng, rates, opp, np.ones(n), np.zeros(n, dtype=bool))
    assert played.mean() > 1.0
    assert benched.sum() == 0
