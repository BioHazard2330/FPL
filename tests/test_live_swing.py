from fpl_agent.models import live_swing as ls


def _man(position, stake, goals=1.0, assists=1.0):
    return {"position": position, "stake": stake, "goals": goals, "assists": assists}


def test_a_goal_by_a_player_you_own_and_the_field_does_not_is_worth_his_goal_and_its_bonus():
    side = [_man("FWD", 1.0, goals=1.0, assists=0.0)]
    assert ls.side_next_goal(side, [], 1) == 4 + ls.BONUS_PER_GOAL


def test_a_template_player_you_do_not_own_costs_you():
    side = [_man("FWD", -1.5, goals=1.0, assists=0.0)]
    assert ls.side_next_goal(side, [], 1) == -1.5 * (4 + ls.BONUS_PER_GOAL)


def test_shares_split_the_goal_and_the_assist_counts_on_nine_goals_in_ten():
    side = [_man("MID", 1.0, goals=3.0, assists=1.0), _man("MID", 0.0, goals=1.0, assists=1.0)]
    want = 0.75 * (5 + ls.BONUS_PER_GOAL) + 0.9 * 0.5 * (3 + ls.BONUS_PER_ASSIST)
    assert abs(ls.side_next_goal(side, [], 1) - want) < 1e-9


def test_conceding_takes_the_clean_sheet_you_hold_more_of_than_the_field():
    attackers = [_man("FWD", 0.0, goals=1.0, assists=0.0)]
    defenders = [{**_man("DEF", 0.5), "cs": 1.0}, {**_man("GKP", 0.5), "cs": 1.0}]
    assert ls.side_next_goal(attackers, defenders, 0) == -(0.5 * 4.5 + 0.5 * 5)
    assert ls.side_next_goal(attackers, defenders, 2) == 0


def test_every_second_goal_conceded_costs_keepers_and_defenders_a_point():
    attackers = [_man("FWD", 0.0, goals=1.0, assists=0.0)]
    defenders = [{**_man("DEF", 1.0), "cs": 1.0}, {**_man("MID", 1.0), "cs": 1.0}]
    assert ls.side_next_goal(attackers, defenders, 1) == -1
    assert ls.side_next_goal(attackers, defenders, 2) == 0


def test_a_clean_sheet_needs_sixty_minutes_and_survives_being_subbed_off():
    assert ls.clean_sheet_holder(70, False, 80)
    assert ls.clean_sheet_holder(20, True, 20)
    assert not ls.clean_sheet_holder(20, False, 80)
    assert not ls.clean_sheet_holder(10, True, 75)
    assert not ls.clean_sheet_holder(40, True, 50, sent_off=True)


def _pick(pid, mult, pos, team=1, vice=False):
    return {"player_id": pid, "multiplier": mult, "is_vice": vice, "position": pos, "team_id": team}


def _squad():
    picks = [_pick(1, 1, "GKP")] + [_pick(i, 1, "DEF") for i in range(2, 6)] + [_pick(6, 2, "MID", team=2), _pick(7, 1, "MID", vice=True)]
    picks += [_pick(i, 1, "MID") for i in (8, 9)] + [_pick(i, 1, "FWD") for i in (10, 11)]
    return picks + [_pick(12, 0, "GKP"), _pick(13, 0, "MID"), _pick(14, 0, "DEF"), _pick(15, 0, "FWD")]


def test_a_captain_who_missed_a_finished_match_passes_the_armband_and_the_bench_comes_on():
    minutes = {i: 90 for i in range(1, 16)} | {6: 0}
    mine, subs = ls.effective_multipliers(_squad(), minutes, {1: True, 2: True})
    assert mine[6] == 0 and mine[7] == 2 and mine[13] == 1 and subs == [(6, 13)]


def test_nothing_changes_while_a_starters_match_is_still_to_come():
    minutes = {i: 90 for i in range(1, 16)} | {6: 0}
    mine, subs = ls.effective_multipliers(_squad(), minutes, {1: True, 2: False})
    assert mine[6] == 2 and mine[7] == 1 and subs == []


def test_no_side_to_cheer_when_the_next_goals_are_close():
    assert ls.cheer_for(1.0, 1.2) is None
    assert ls.cheer_for(3.0, 1.0) == "home"
    assert ls.cheer_for(-2.0, 1.0) == "away"
