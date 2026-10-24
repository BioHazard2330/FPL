"""The two endpoints behind the eye test and the live analyst: input validation, caching, and the comparison with the stored plan."""
import pytest

from fpl_agent.monitoring.api import livestory_payload, viewplan_payload


def test_scales_are_parsed_and_bounded():
    assert viewplan_payload.parse_scales("12:0.75,411:1.1") == {12: 0.75, 411: 1.1}
    assert viewplan_payload.parse_scales("") == {} and viewplan_payload.parse_scales(None) == {}
    for bad in ("12", "x:1", "12:4", "12:-0.1"):
        with pytest.raises(LookupError):
            viewplan_payload.parse_scales(bad)
    with pytest.raises(LookupError):
        viewplan_payload.parse_scales(",".join(f"{i}:1" for i in range(13)))


def _patch_viewplan(monkeypatch, stored_moves, planned_moves, calls):
    class _Conn:
        def close(self):
            pass

    monkeypatch.setattr("fpl_agent.database.connection.get_connection", lambda: _Conn())
    stored = ({"moves": [{"out": {"player_id": o}, "into": {"player_id": i}} for o, i in stored_moves]}, "t0", 7) if stored_moves is not None else None
    monkeypatch.setattr("fpl_agent.optimization.week_plan.latest_week_plan", lambda conn: stored)

    def plan_with_view(conn, scales):
        calls.append(dict(scales))
        return {"moves": [{"out": {"player_id": o}, "into": {"player_id": i}, "gain": 2.0} for o, i in planned_moves], "declined": [], "plan_total": 1.0, "roll_total": 0.0, "gain_vs_roll": 1.0}

    monkeypatch.setattr("fpl_agent.optimization.week_plan.plan_with_view", plan_with_view)


def test_a_view_that_makes_the_same_moves_says_so_and_a_repeat_is_served_from_the_cache(monkeypatch):
    viewplan_payload._CACHE.clear()
    calls: list = []
    _patch_viewplan(monkeypatch, [(1, 2)], [(1, 2)], calls)
    first = viewplan_payload.build_view_plan(None, {"scales": "5:0.9"})
    second = viewplan_payload.build_view_plan(None, {"scales": "5:0.9"})
    assert first["same_as_stored"] is True and second["same_as_stored"] is True
    assert calls == [{5: 0.9}]


def test_a_view_that_changes_the_moves_is_not_the_stored_plan(monkeypatch):
    viewplan_payload._CACHE.clear()
    calls: list = []
    _patch_viewplan(monkeypatch, [(1, 2)], [], calls)
    out = viewplan_payload.build_view_plan(None, {"scales": "2:0.5"})
    assert out["same_as_stored"] is False and out["stored_moves"] == [(1, 2)]


def test_a_bad_scale_is_rejected_before_any_planning(monkeypatch):
    viewplan_payload._CACHE.clear()
    calls: list = []
    _patch_viewplan(monkeypatch, [], [], calls)
    with pytest.raises(LookupError):
        viewplan_payload.build_view_plan(None, {"scales": "9:7"})
    assert calls == []


def test_the_live_story_needs_a_real_match_id_and_a_match_in_play(monkeypatch):
    livestory_payload._CACHE.clear()
    with pytest.raises(LookupError):
        livestory_payload.build_live_story(None, {"id": "abc"})

    class _Conn:
        def close(self):
            pass

    monkeypatch.setattr("fpl_agent.database.connection.get_connection", lambda: _Conn())
    monkeypatch.setattr("fpl_agent.models.match_analyst.analyse_live", lambda conn, match_id: None)
    with pytest.raises(LookupError):
        livestory_payload.build_live_story(None, {"id": "5"})


def test_a_live_story_is_provisional_and_held_for_a_few_seconds(monkeypatch):
    livestory_payload._CACHE.clear()
    calls: list = []

    class _Conn:
        def close(self):
            pass

    def analyse(conn, match_id):
        calls.append(match_id)
        return {"length": 30, "headline": "Minute 30"}

    monkeypatch.setattr("fpl_agent.database.connection.get_connection", lambda: _Conn())
    monkeypatch.setattr("fpl_agent.models.match_analyst.analyse_live", analyse)
    a = livestory_payload.build_live_story(None, {"id": "9"})
    b = livestory_payload.build_live_story(None, {"id": "9"})
    assert a["provisional"] is True and a["minute"] == 30 and b is a
    assert calls == [9]
