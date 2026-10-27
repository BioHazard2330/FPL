from fpl_agent.models.scouting import _in_box, _percentile, _profiles, _six_yard


def test_box_geometry_on_a_105_by_68_pitch():
    assert _in_box(95, 34) and _in_box(89, 14.5)
    assert not _in_box(80, 34) and not _in_box(95, 5)
    assert _six_yard(101, 30) and not _six_yard(97, 34)


def test_percentile_is_the_share_of_the_pool_at_or_below():
    assert _percentile(5, [1, 2, 3, 4, 5]) == 100
    assert _percentile(1, [1, 2, 3, 4, 5]) == 20
    assert _percentile(3, []) == 50


def test_profiles_are_rules_over_percentiles():
    fwd = _profiles("FWD", {"box_share": 95, "xg_per_shot": 86, "npxg90": 100, "xa90": 20, "header_share": 100}, {"box_share": 0.97})
    assert fwd[:2] == ["Penalty-box finisher", "Goal threat"] and "Aerial threat" in fwd
    gk = _profiles("GKP", {"prevented90": 90, "saves90": 10}, {})
    assert gk == ["Shot-stopper"]
    full_back = _profiles("DEF", {"xa90": 85, "defcon90": 30}, {})
    assert full_back == ["Attacking full-back"]
