import pytest

from fpl_agent.models import matchup_lab as ml


def _profiles():
    return {
        1: {"matches": 6, "for": {"corners": 3.0, "open play": 6.0}, "against": {"corners": 0.6, "open play": 6.0}},
        2: {"matches": 6, "for": {"corners": 0.6, "open play": 6.0}, "against": {"corners": 3.0, "open play": 6.0}},
        3: {"matches": 6, "for": {"corners": 1.2, "open play": 6.0}, "against": {"corners": 1.2, "open play": 6.0}},
    }


def test_league_means_are_per_team_match():
    means = ml.league_means(_profiles())
    assert means["corners"] == pytest.approx((3.0 + 0.6 + 1.2) / 18)
    assert means["open play"] == pytest.approx(1.0)
    assert ml.league_means({}) == {s: 0.0 for s in ml.SOURCES}


def test_shrunk_ratio_moves_part_of_the_way_to_the_observed_ratio():
    league = 0.2
    observed = ml.shrunk_ratio(6 * 0.4, 6, league)
    assert 1.0 < observed < 2.0
    assert observed == pytest.approx((2.4 + 8 * 0.2) / (14 * 0.2))
    assert ml.shrunk_ratio(0.0, 0, league) == pytest.approx(1.0)
    assert ml.shrunk_ratio(5.0, 5, 0.0) == 1.0


def test_a_corner_attack_against_a_corner_leaking_defence_gains_xg_over_the_league_average():
    p = _profiles()
    means = ml.league_means(p)
    lens = ml.fixture_lens(p, means, 1, 2)
    corners_home = next(r for r in lens["home"] if r["source"] == "corners")
    corners_away = next(r for r in lens["away"] if r["source"] == "corners")
    assert corners_home["shift"] > 0.05
    assert corners_away["shift"] < 0
    assert lens["headline"]["source"] == "corners" and lens["headline"]["side"] == "home"


def test_a_fixture_between_average_sides_has_no_headline():
    p = _profiles()
    p[1] = {"matches": 6, "for": {"corners": 1.2, "open play": 6.0}, "against": {"corners": 1.2, "open play": 6.0}}
    p[2] = dict(p[1])
    lens = ml.fixture_lens(p, ml.league_means(p), 1, 2)
    assert lens["headline"] is None


def test_unknown_teams_use_the_league_average():
    lens = ml.fixture_lens({}, {s: 0.1 for s in ml.SOURCES}, 8, 9)
    assert all(r["attack"] == 1.0 and r["defence"] == 1.0 for r in lens["home"])
