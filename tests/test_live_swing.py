from fpl_agent.models import live_swing as ls


def _man(position, stake, goals=1.0, assists=1.0):
    return {"position": position, "stake": stake, "goals": goals, "assists": assists}


def test_a_goal_by_a_player_you_own_and_the_field_does_not_is_worth_his_full_goal():
    side = [_man("FWD", 1.0, goals=1.0, assists=0.0)]
    assert ls.side_next_goal(side, [], False) == 4


def test_a_template_player_you_do_not_own_costs_you():
    side = [_man("FWD", -1.5, goals=1.0, assists=0.0)]
    assert ls.side_next_goal(side, [], False) == -6


def test_shares_split_the_goal_and_the_assist_counts_on_nine_goals_in_ten():
    side = [_man("MID", 1.0, goals=3.0, assists=1.0), _man("MID", 0.0, goals=1.0, assists=1.0)]
    assert abs(ls.side_next_goal(side, [], False) - (0.75 * 5 + 0.9 * 0.5 * 3)) < 1e-9


def test_conceding_takes_the_clean_sheet_you_hold_more_of_than_the_field():
    attackers = [_man("FWD", 0.0, goals=1.0, assists=0.0)]
    defenders = [_man("DEF", 0.5), _man("GKP", 0.5)]
    assert ls.side_next_goal(attackers, defenders, True) == -4
    assert ls.side_next_goal(attackers, defenders, False) == 0


def test_no_side_to_cheer_when_the_next_goals_are_close():
    assert ls.cheer_for(1.0, 1.2) is None
    assert ls.cheer_for(3.0, 1.0) == "home"
    assert ls.cheer_for(-2.0, 1.0) == "away"
