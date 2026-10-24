from fpl_agent.monitoring.api.weekplan_payload import lineup_changes


def _p(pid, xp, name=None):
    return {"player_id": pid, "name": name or f"P{pid}", "position": "MID", "team_id": 1, "xp": xp}


def _lineup(starting, bench, captain, vice, total):
    return {"starting": starting, "bench": bench, "captain_id": captain, "vice_id": vice, "xp_total": total}


def test_no_lineup_set_means_no_changes_to_report():
    best = _lineup([_p(1, 5.0)], [], 1, None, 5.0)

    assert lineup_changes(None, best) is None


def test_a_better_player_on_the_bench_is_reported_as_a_swap_with_the_player_he_replaces():
    as_set = _lineup([_p(1, 5.0), _p(2, 1.7, "Davis")], [_p(3, 4.8, "Bogle")], 1, None, 6.7)
    best = _lineup([_p(1, 5.0), _p(3, 4.8, "Bogle")], [_p(2, 1.7, "Davis")], 1, None, 9.8)

    changes = lineup_changes(as_set, best)

    assert [p["name"] for p in changes["bring_in"]] == ["Bogle"]
    assert [p["name"] for p in changes["take_out"]] == ["Davis"]
    assert changes["xp_gain"] == 3.1
    assert changes["worth_changing"] is True


def test_an_identical_lineup_needs_no_change():
    lineup = _lineup([_p(1, 5.0), _p(2, 4.0)], [_p(3, 3.0)], 1, 2, 9.0)

    changes = lineup_changes(lineup, lineup)

    assert changes["bring_in"] == [] and changes["take_out"] == []
    assert changes["worth_changing"] is False
    assert changes["xp_gain"] == 0


def test_a_different_captain_alone_is_worth_changing():
    as_set = _lineup([_p(1, 5.0), _p(2, 4.0)], [], 2, 1, 13.0)
    best = _lineup([_p(1, 5.0), _p(2, 4.0)], [], 1, 2, 14.0)

    changes = lineup_changes(as_set, best)

    assert changes["worth_changing"] is True
    assert changes["captain_from"]["player_id"] == 2
    assert changes["captain_to"]["player_id"] == 1


def test_the_form_board_orders_the_squad_coldest_first_and_stamps_players_in_moves(monkeypatch):
    from fpl_agent.monitoring.api import weekplan_payload

    readings = {
        1: {"label": "STEADY", "ratio": 1.0}, 2: {"label": "COLD", "ratio": 0.3},
        3: {"label": "HOT", "ratio": 1.8}, 4: {"label": "COOLING", "ratio": 0.6},
    }
    monkeypatch.setattr("fpl_agent.models.form_watch.form_watch", lambda conn, ids: {i: dict(readings[i]) for i in ids if i in readings})

    class _Rows(list):
        pass

    class _Conn:
        def execute(self, sql, args=()):
            return _Rows({"id": i, "web_name": f"P{i}", "element_type": 3} for i in args)

    payload = {"moves": [{"out": {"player_id": 2}, "into": {"player_id": 4}}], "declined": []}
    weekplan_payload._attach_form(_Conn(), payload, [1, 2, 3])

    assert [r["name"] for r in payload["form_board"]] == ["P2", "P3", "P1"]
    assert payload["moves"][0]["out"]["form"]["label"] == "COLD" and payload["moves"][0]["into"]["form"]["label"] == "COOLING"
