from types import SimpleNamespace

from fpl_agent.optimization.squad import PlayerCandidate
from fpl_agent.optimization.week_plan import pick_captains, prefer_current_eleven, select_moves

EVENT = 7


def _plan(total, moves, proven=True):
    steps = [
        SimpleNamespace(event=EVENT, player_out_id=o, player_in_id=i) for o, i in moves
    ]
    return SimpleNamespace(sequence=SimpleNamespace(total_net_ev=total, steps=steps), proven_optimal=proven)


def _solver(totals_by_k, moves_by_k):
    calls = []

    def solve(k, forced_in, forced_out):
        calls.append((k, forced_in, forced_out))
        return _plan(totals_by_k[k], moves_by_k[k])

    return solve, calls


def test_moves_are_added_while_each_one_earns_its_keep():
    solve, _ = _solver(
        {0: 100.0, 1: 105.0, 2: 107.0, 3: 107.4},
        {0: [], 1: [(1, 11)], 2: [(1, 11), (2, 12)], 3: [(1, 11), (2, 12), (3, 13)]},
    )

    selection = select_moves(solve, EVENT, min_move_gain=1.5)

    assert [(o, i) for o, i, _ in selection.accepted] == [(1, 11), (2, 12)]
    assert [g for _, _, g in selection.accepted] == [5.0, 2.0]
    assert [(o, i) for o, i, _ in selection.declined] == [(3, 13)]
    assert selection.declined[0][2] == 0.4


def test_a_first_move_under_the_bar_means_roll():
    solve, _ = _solver({0: 100.0, 1: 100.9}, {0: [], 1: [(1, 11)]})

    selection = select_moves(solve, EVENT, min_move_gain=1.5)

    assert selection.accepted == []
    assert len(selection.declined) == 1
    assert selection.roll_total == 100.0


def test_earlier_moves_are_pinned_when_the_next_one_is_priced():
    solve, calls = _solver(
        {0: 100.0, 1: 105.0, 2: 108.0},
        {0: [], 1: [(1, 11)], 2: [(1, 11), (2, 12)]},
    )

    select_moves(solve, EVENT, min_move_gain=1.5, max_moves=2)

    k2 = next(c for c in calls if c[0] == 2)
    assert k2[1] == frozenset({11})
    assert k2[2] == frozenset({1})


def test_the_curve_reports_gain_over_rolling_for_every_count_tried():
    solve, _ = _solver(
        {0: 100.0, 1: 105.0, 2: 107.0, 3: 107.4},
        {0: [], 1: [(1, 11)], 2: [(1, 11), (2, 12)], 3: [(1, 11), (2, 12), (3, 13)]},
    )

    selection = select_moves(solve, EVENT, min_move_gain=1.5)

    assert [(c.moves, c.gain_vs_roll) for c in selection.curve] == [(0, 0.0), (1, 5.0), (2, 7.0), (3, 7.4)]


def test_an_unsolvable_roll_gives_no_plan():
    def solve(k, forced_in, forced_out):
        return SimpleNamespace(sequence=None, proven_optimal=False)

    assert select_moves(solve, EVENT, min_move_gain=1.5) is None


def test_the_plan_is_only_proven_if_every_solve_was():
    plans = {0: _plan(100.0, [], True), 1: _plan(105.0, [(1, 11)], False), 2: _plan(105.2, [(1, 11), (2, 12)], True)}

    def solve(k, forced_in, forced_out):
        return plans[k]

    assert select_moves(solve, EVENT, min_move_gain=1.5).proven is False


def _candidate(pid, team_id, xp):
    return PlayerCandidate(
        player_id=pid, web_name=f"P{pid}", position="MID", team_id=team_id, team_short="T", price_tenths=50,
        xp=xp, median=xp, floor=0.0, ceiling=10.0, confidence="MEDIUM", expected_minutes=90.0,
    )


def _projection(goals, assists):
    return SimpleNamespace(components=SimpleNamespace(goals=goals, assists=assists))


def test_a_clear_top_projection_takes_the_armband():
    starting = [_candidate(1, 1, 8.0), _candidate(2, 2, 5.0)]
    cache = {(1, EVENT): _projection(1.0, 0.5), (2, EVENT): _projection(4.0, 0.0)}

    captain, vice = pick_captains(starting, cache, EVENT)

    assert captain.player_id == 1
    assert vice.player_id == 2


def test_near_tied_projections_go_to_the_player_whose_points_come_from_goals_and_assists():
    starting = [_candidate(1, 1, 6.7), _candidate(2, 2, 6.5)]
    cache = {(1, EVENT): _projection(2.4, 1.1), (2, EVENT): _projection(3.9, 0.3)}

    captain, _ = pick_captains(starting, cache, EVENT)

    assert captain.player_id == 2


def test_vice_prefers_a_different_club_from_the_captain():
    starting = [_candidate(1, 1, 7.0), _candidate(2, 1, 6.9), _candidate(3, 2, 5.0)]
    cache = {(p, EVENT): _projection(1.0, 0.0) for p in (1, 2, 3)}

    captain, vice = pick_captains(starting, cache, EVENT)

    assert captain.player_id == 1
    assert vice.player_id == 3


def test_no_starters_means_no_captain():
    assert pick_captains([], {}, EVENT) == (None, None)


def _positioned(pid, position, xp):
    return PlayerCandidate(
        player_id=pid, web_name=f"P{pid}", position=position, team_id=pid, team_short="T", price_tenths=50,
        xp=xp, median=xp, floor=0.0, ceiling=10.0, confidence="MEDIUM", expected_minutes=90.0,
    )


def test_a_marginally_better_player_does_not_displace_the_one_already_picked():
    kinsky, verbruggen = _positioned(1, "GKP", 3.7), _positioned(2, "GKP", 3.6)

    start, bench = prefer_current_eleven([kinsky], [verbruggen], current_ids={2})

    assert [c.player_id for c in start] == [2]
    assert [c.player_id for c in bench] == [1]


def test_a_clearly_better_player_does_displace_the_current_pick():
    bogle, davis = _positioned(1, "DEF", 4.8), _positioned(2, "DEF", 1.7)

    start, bench = prefer_current_eleven([bogle], [davis], current_ids={2})

    assert [c.player_id for c in start] == [1]
    assert [c.player_id for c in bench] == [2]


def test_a_swap_is_never_made_across_positions():
    forward, defender = _positioned(1, "FWD", 4.0), _positioned(2, "DEF", 3.9)

    start, bench = prefer_current_eleven([forward], [defender], current_ids={2})

    assert [c.player_id for c in start] == [1]


def test_with_no_current_eleven_nothing_changes():
    a, b = _positioned(1, "MID", 5.0), _positioned(2, "MID", 4.9)

    assert prefer_current_eleven([a], [b], current_ids=set()) == ([a], [b])


def test_chip_outlook_reports_double_gameweeks_by_team(db_conn):
    from fpl_agent.optimization.week_plan import build_chip_outlook

    for tid, short in ((1, "ARS"), (2, "MCI"), (3, "AVL")):
        db_conn.execute(
            "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?, ?, ?, ?, 't')",
            (tid, 100 + tid, short, short),
        )
    db_conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, "
        "is_next, updated_at) VALUES (9, 'Gameweek 9', 't', 0, 0, 0, 0, 0, 't')"
    )
    for fid, (h, a, ev) in enumerate([(1, 2, 9), (3, 1, 9), (2, 3, 9)], start=1):
        db_conn.execute(
            "INSERT INTO fixtures (id, code, event, team_h, team_a, finished, started, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 0, 0, 't')", (fid, fid, ev, h, a),
        )
    db_conn.commit()

    outlook = build_chip_outlook(db_conn, 7, 6.2, horizon=4)

    assert outlook["double_gameweeks"] == [{"event": 9, "teams": ["ARS", "AVL", "MCI"]}]
    assert {"event": 7, "teams": ["ARS", "AVL", "MCI"]} in outlook["blank_gameweeks"]
    assert outlook["bench_boost_this_week"] == 6.2


def _detail(**over):
    from fpl_agent.optimization import week_plan

    base = {
        "squad_ids": [1, 2, 3], "bank_tenths": 3, "event": 7, "free_transfers": 5,
        "moves": [{"into": {"player_id": 9}}], "declined": [], "calibration": week_plan.calibration_id(),
    }
    base.update(over)
    return base


def _state(**over):
    base = {"event": 6, "squad_ids": [1, 2, 3], "bank_tenths": 3, "free_transfers": 5}
    base.update(over)
    return base


def test_a_plan_matching_the_current_state_is_not_stale(db_conn, monkeypatch):
    from fpl_agent.optimization import week_plan

    monkeypatch.setattr(week_plan, "light_squad_state", lambda conn: _state())

    assert week_plan.week_plan_staleness(db_conn, _detail(), "2026-10-15T00:00:00+00:00") == []


def test_each_changed_input_is_named_as_a_reason(db_conn, monkeypatch):
    from fpl_agent.optimization import week_plan

    monkeypatch.setattr(
        week_plan, "light_squad_state",
        lambda conn: _state(squad_ids=[1, 2, 4], bank_tenths=10, event=7, free_transfers=4),
    )

    reasons = week_plan.week_plan_staleness(db_conn, _detail(), "2026-10-15T00:00:00+00:00")

    assert len(reasons) == 4
    assert any("squad" in r for r in reasons)
    assert any("bank" in r for r in reasons)
    assert any("gameweek" in r for r in reasons)
    assert any("free transfers" in r for r in reasons)


def test_no_synced_squad_is_its_own_reason(db_conn, monkeypatch):
    from fpl_agent.optimization import week_plan

    monkeypatch.setattr(week_plan, "light_squad_state", lambda conn: None)

    assert week_plan.week_plan_staleness(db_conn, _detail(), "t") == ["no synced squad"]


def test_a_high_severity_change_to_a_transfer_target_makes_the_plan_stale(db_conn, monkeypatch):
    from fpl_agent.optimization import week_plan

    db_conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1, 1, 'T', 'T', 't')")
    db_conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1, 'Midfielder', 'MID', 'Midfielders', 't')"
    )
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (9, 9, 'Cherki', 1, 1, 'a', 't')"
    )
    db_conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, sources, "
        "confidence, severity, action_required) VALUES ('status_change', 'player', 9, 'a', 'i', "
        "'2026-10-16T00:00:00+00:00', '[]', 'official', 'HIGH', 0)"
    )
    db_conn.commit()
    monkeypatch.setattr(week_plan, "light_squad_state", lambda conn: _state())

    reasons = week_plan.week_plan_staleness(db_conn, _detail(), "2026-10-15T00:00:00+00:00")

    assert len(reasons) == 1
    assert "Cherki" in reasons[0] and "status change" in reasons[0]


def _ref(**over):
    from fpl_agent.optimization.week_plan import PlayerRef

    base = dict(
        player_id=1, name="Player", position="MID", team_short="T", team_id=1, price_tenths=50, xp_next=4.0,
        xp_horizon=20.0, start_percent=90, price_trend="STABLE", solio_next=None,
    )
    base.update(over)
    return PlayerRef(**base)


def test_a_rising_target_is_an_early_move():
    from fpl_agent.optimization.week_plan import move_timing

    timing, note = move_timing(_ref(name="Out"), _ref(name="Cherki", price_trend="RISE_LIKELY"))

    assert timing == "early"
    assert "Cherki" in note and "rise" in note


def test_a_falling_player_being_sold_is_also_early():
    from fpl_agent.optimization.week_plan import move_timing

    timing, note = move_timing(_ref(name="Gibbs-White", price_trend="FALL_LIKELY"), _ref())

    assert timing == "early"
    assert "fall" in note


def test_an_open_rotation_call_means_wait_for_team_news():
    from fpl_agent.optimization.week_plan import move_timing

    timing, note = move_timing(_ref(name="Gvardiol", start_percent=24), _ref())

    assert timing == "late"
    assert "24%" in note


def test_a_moving_price_and_an_open_rotation_call_is_marked_as_a_trade_off():
    from fpl_agent.optimization.week_plan import move_timing

    timing, _ = move_timing(_ref(start_percent=24), _ref(price_trend="RISE_LIKELY"))

    assert timing == "split"


def test_nothing_pressing_means_no_timing_advice():
    from fpl_agent.optimization.week_plan import move_timing

    assert move_timing(_ref(), _ref()) == ("any", "")



def _plan_with(moves, event=7):
    from types import SimpleNamespace

    return SimpleNamespace(
        event=event,
        moves=[
            SimpleNamespace(out=SimpleNamespace(player_id=o, name=f"P{o}"), into=SimpleNamespace(player_id=i, name=f"P{i}"))
            for o, i in moves
        ],
    )


def _detail_with(moves, event=7):
    return {"event": event, "moves": [{"out": {"player_id": o, "name": f"P{o}"}, "into": {"player_id": i, "name": f"P{i}"}} for o, i in moves]}


def test_a_changed_move_set_is_recorded_as_a_high_severity_event(db_conn):
    from fpl_agent.optimization.week_plan import announce_plan_change

    changed = announce_plan_change(db_conn, _detail_with([(1, 11)]), _plan_with([(1, 12)]), "Cherki: status change")

    row = db_conn.execute("SELECT event_type, severity, old_value, new_value, fpl_impact FROM change_events").fetchone()
    assert changed is True
    assert row["event_type"] == "week_plan_change" and row["severity"] == "HIGH"
    assert "P11" in row["old_value"] and "P12" in row["new_value"]
    assert "Cherki" in row["fpl_impact"]


def test_a_rebuild_that_lands_on_the_same_moves_is_silent(db_conn):
    from fpl_agent.optimization.week_plan import announce_plan_change

    assert announce_plan_change(db_conn, _detail_with([(1, 11)]), _plan_with([(1, 11)]), "12h old") is False
    assert db_conn.execute("SELECT COUNT(*) FROM change_events").fetchone()[0] == 0


def test_the_first_plan_of_a_gameweek_is_silent(db_conn):
    from fpl_agent.optimization.week_plan import announce_plan_change

    assert announce_plan_change(db_conn, None, _plan_with([(1, 11)]), "none yet") is False
    assert announce_plan_change(db_conn, _detail_with([(1, 11)], event=6), _plan_with([(1, 12)]), "new gameweek") is False


def test_the_plan_change_event_never_makes_a_plan_look_stale(db_conn, monkeypatch):
    from fpl_agent.optimization import week_plan
    from fpl_agent.optimization.week_plan import announce_plan_change

    announce_plan_change(db_conn, _detail_with([(1, 11)]), _plan_with([(1, 12)]), "reason")
    monkeypatch.setattr(week_plan, "light_squad_state", lambda conn: _state())

    assert week_plan.week_plan_staleness(db_conn, _detail(), "2000-01-01T00:00:00+00:00") == []


def test_alternatives_are_priced_against_a_plan_that_never_buys_the_banned_player():
    from fpl_agent.optimization.week_plan import find_alternatives

    calls = []

    def solve(k, fin, fout, scale, banned):
        calls.append((k, fin, fout, banned))
        if k == 0:
            return _plan(100.0, [])
        if 11 in banned and 12 in banned:
            return _plan(101.0, [(1, 13)])
        if 11 in banned:
            return _plan(102.5, [(1, 12)])
        return _plan(105.0, [(1, 11)])

    found = find_alternatives(solve, [(1, 11)], EVENT, count=2)

    assert found == [[(1, 12, 2.5), (1, 13, 1.0)]]
    assert calls[0][3] == frozenset({11})
    assert calls[2][3] == frozenset({11, 12})
    assert calls[0][0] == 0


def test_an_alternative_worth_nothing_is_not_listed():
    from fpl_agent.optimization.week_plan import find_alternatives

    def solve(k, fin, fout, scale, banned):
        return _plan(100.0, [(1, 12)] if k else [])

    assert find_alternatives(solve, [(1, 11)], EVENT) == [[]]


def test_a_failing_search_leaves_the_move_with_no_alternatives():
    from fpl_agent.optimization.week_plan import find_alternatives

    def solve(*args):
        raise RuntimeError("solver down")

    assert find_alternatives(solve, [(1, 11)], EVENT) == [[]]


def _deadline_in(conn, hours):
    from datetime import datetime, timedelta, timezone

    stamp = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, updated_at) "
        "VALUES (7, 'GW7', ?, 0, 0, 0, 0, 1, 't')", (stamp,),
    )


def test_a_plan_is_allowed_to_get_older_the_further_the_deadline(db_conn):
    from fpl_agent.optimization.week_plan import refresh_after_hours

    _deadline_in(db_conn, 60)
    assert refresh_after_hours(db_conn) == 12
    _deadline_in(db_conn, 20)
    assert refresh_after_hours(db_conn) == 6
    _deadline_in(db_conn, 5)
    assert refresh_after_hours(db_conn) == 3


def test_fresh_odds_after_the_plan_trigger_a_rebuild_only_in_the_final_day(db_conn):
    from datetime import datetime, timedelta, timezone

    from fpl_agent.optimization.week_plan import _odds_newer_than

    now = datetime.now(timezone.utc)
    made = (now - timedelta(hours=2)).isoformat()
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('odds_api_last_synced_at', ?, ?)",
        ((now - timedelta(hours=1)).isoformat(),) * 2,
    )
    _deadline_in(db_conn, 10)
    assert _odds_newer_than(db_conn, made) is True
    assert _odds_newer_than(db_conn, (now - timedelta(minutes=30)).isoformat()) is False
    _deadline_in(db_conn, 70)
    assert _odds_newer_than(db_conn, made) is False


def test_a_plan_made_under_a_different_calibration_is_stale(db_conn, monkeypatch):
    from fpl_agent.optimization import week_plan

    monkeypatch.setattr(week_plan, "light_squad_state", lambda conn: _state())
    reasons = week_plan.week_plan_staleness(db_conn, _detail(calibration="calibrated-v2|old"), "2026-10-15T00:00:00+00:00")
    assert reasons == ["the projection model's calibration has changed"]
    missing = _detail()
    del missing["calibration"]
    assert week_plan.week_plan_staleness(db_conn, missing, "2026-10-15T00:00:00+00:00") == ["the projection model's calibration has changed"]
