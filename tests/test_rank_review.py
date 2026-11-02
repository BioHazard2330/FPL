import pytest

from fpl_agent.models import pundit
from fpl_agent.optimization.rank_review import season_chance


def test_more_expected_points_always_raise_the_chance():
    assert season_chance(77, 29, 2.0, 10.0, 0.0, 2.6, 10.0) > season_chance(77, 29, 0.0, 10.0, 0.0, 2.6, 10.0)


def test_later_horizon_gain_counts_like_this_weeks_points():
    assert season_chance(77, 29, 0.0, 10.0, 3.0, 2.6, 10.0) == pytest.approx(season_chance(77, 29, 3.0, 10.0, 0.0, 2.6, 10.0))


def test_behind_the_target_a_wider_spread_helps_and_ahead_of_it_a_narrower_one_does():
    behind = (200, 5, 0.0)
    assert season_chance(*behind, 30.0, 0.0, 0.0, 10.0) > season_chance(*behind, 5.0, 0.0, 0.0, 10.0)
    ahead = (-50, 5, 0.0)
    assert season_chance(*ahead, 5.0, 0.0, 0.0, 10.0) > season_chance(*ahead, 30.0, 0.0, 0.0, 10.0)


def _side(pid, name, team_code, xp_gw, read="mixed", start=90, solio=None, **extra):
    return {"player_id": pid, "name": name, "team_code": team_code, "team_short": f"T{team_code}", "position": "MID",
            "xp_by_gw": xp_gw, "xp_next": xp_gw[0], "start_percent": start, "solio_next": solio, "duties": [],
            "football_read": {"verdict": {"label": read, "text": f"{name} read."}}, **extra}


def _fx(diffs):
    return [{"opponent_short": f"O{i}", "is_home": i % 2 == 0, "difficulty": d} for i, d in enumerate(diffs)]


def test_a_move_every_lens_backs_is_strong():
    move = {"out": _side(1, "Old", 10, [3, 3, 3], read="against him", solio=3.0),
            "into": _side(2, "New", 20, [5, 5, 5], read="backs him", solio=5.0),
            "gain": 6.0, "confidence": {"win_prob": 0.7, "mean_diff": 6, "p10": -5, "p90": 15, "trials": 4000}}
    b = pundit.move_brief(move, {"20": _fx([2, 2, 2]), "10": _fx([4, 4, 4])}, {}, {}, {}, 3)
    assert b["grade"] == "strong" and not b["against"]


def test_a_move_the_fixtures_read_and_replays_oppose_is_doubtful():
    move = {"out": _side(1, "Old", 10, [3, 3, 3], read="backs him"),
            "into": _side(2, "New", 20, [3.5, 3.5, 3.5], start=55),
            "gain": 1.6, "confidence": {"win_prob": 0.48, "mean_diff": 1, "p10": -9, "p90": 10, "trials": 4000}}
    b = pundit.move_brief(move, {"20": _fx([4, 5, 4]), "10": _fx([2, 2, 3])}, {}, {}, {}, 3)
    assert b["grade"] == "doubtful"
    assert any(lz["key"] == "fixtures" and lz["lean"] == -1 for lz in b["lenses"])


def test_form_streaks_are_context_never_counted():
    base = {"out": _side(1, "Old", 10, [3]), "into": _side(2, "New", 20, [3.2]), "gain": 0.2, "stress": None}
    hot = {**base, "into": {**base["into"], "form": {"label": "HOT"}}}
    assert pundit.move_brief(hot, {}, {}, {}, {}, 1)["score"] == pundit.move_brief(base, {}, {}, {}, {}, 1)["score"]


def test_the_captain_brief_names_the_field_favourite_when_the_plan_goes_against_it():
    lineup = {"captain_id": 4, "starting": [
        {"player_id": 4, "name": "Gabriel", "xp": 7.7, "team_code": 3},
        {"player_id": 411, "name": "Haaland", "xp": 6.3, "team_code": 43},
    ]}
    rank = {"captains": [
        {"player_id": 4, "field_captain_share": 0.0, "field_eo": 0.15, "chance": 0.483, "week_sd": 13.4},
        {"player_id": 411, "field_captain_share": 0.91, "field_eo": 1.9, "chance": 0.471, "week_sd": 9.2},
    ]}
    b = pundit.captain_brief(lineup, rank, {}, {})
    assert b["captain_id"] == 4
    assert any("differential" in line and "Haaland" in line for line in b["lines"])
