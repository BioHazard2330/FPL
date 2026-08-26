from fpl_agent.optimization.chips import eligible_chips

_ROWS = [
    (1, "wildcard", 1, 2, 19, "transfer"),
    (2, "wildcard", 1, 20, 38, "transfer"),
    (3, "freehit", 1, 2, 19, "transfer"),
    (4, "bboost", 1, 1, 19, "team"),
    (5, "3xc", 1, 1, 19, "team"),
]


def _seed(conn):
    now = "t0"
    conn.execute(
        "INSERT INTO rules (rule_key,season,version,effective_date,source,value) VALUES ('dummy','2026-27',1,?,?,?)",
        (now, "fpl_api_bootstrap", "1"),
    )
    for id_, name, number, start, stop, ctype in _ROWS:
        conn.execute(
            "INSERT INTO chip_windows (id,name,number,start_event,stop_event,chip_type,season,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (id_, name, number, start, stop, ctype, "2026-27", now),
        )
    conn.commit()


def test_eligible_chips_first_half(db_conn):
    _seed(db_conn)
    windows = {(w.name, w.start_event): w.eligible_now for w in eligible_chips(db_conn, event=5)}

    assert windows[("wildcard", 2)] is True
    assert windows[("wildcard", 20)] is False
    assert windows[("bboost", 1)] is True


def test_eligible_chips_second_half(db_conn):
    _seed(db_conn)
    windows = {(w.name, w.start_event): w.eligible_now for w in eligible_chips(db_conn, event=25)}

    assert windows[("wildcard", 20)] is True
    assert windows[("wildcard", 2)] is False
    assert windows[("bboost", 1)] is False


def test_eligible_chips_gw1_excludes_wildcard_and_freehit(db_conn):
    _seed(db_conn)
    windows = {(w.name, w.start_event): w.eligible_now for w in eligible_chips(db_conn, event=1)}

    assert windows[("wildcard", 2)] is False
    assert windows[("freehit", 2)] is False
    assert windows[("bboost", 1)] is True
    assert windows[("3xc", 1)] is True


import numpy as np

from fpl_agent.models.scenario_engine import ScenarioOutcome
from fpl_agent.optimization.chips import (
    _bench_boost_trial_values,
    _triple_captain_trial_values,
)


def _seed_squad_for_bench_boost(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, "
        "squad_min_play, squad_max_play, updated_at) VALUES "
        "(1,'Goalkeeper','GKP','Goalkeepers',1,1,'t0'), (4,'Forward','FWD','Forwards',1,3,'t0')"
    )
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','t0')")
    conn.executemany(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) VALUES (?,?,?,1,?,'a','t0')",
        [(1, 1, "GK1", 1), (2, 2, "FWD_starter", 4), (3, 3, "FWD_bench", 4)],
    )
    conn.commit()


def test_bench_boost_trial_values_sums_only_bench_points(db_conn, monkeypatch):
    _seed_squad_for_bench_boost(db_conn)
    import fpl_agent.optimization.chips as chips_mod

    # Force a known starting XI / bench split rather than depending on live xP -
    # keeps this a pure wiring test of the trial-summing logic.
    from fpl_agent.optimization.squad import PlayerCandidate, StartingXI

    def fake_pick_xi(conn, squad):
        starter = next(c for c in squad if c.player_id == 2)
        bench_player = next(c for c in squad if c.player_id == 3)
        gk = next(c for c in squad if c.player_id == 1)
        return StartingXI(starting=[gk, starter], bench=[bench_player], captain=starter, vice_captain=gk)

    monkeypatch.setattr(chips_mod, "pick_starting_xi", fake_pick_xi)

    scenario_draw = [
        ScenarioOutcome(trial_index=0, points_by_event_player={(10, 1): 2.0, (10, 2): 6.0, (10, 3): 9.0}),
        ScenarioOutcome(trial_index=1, points_by_event_player={(10, 1): 2.0, (10, 2): 4.0, (10, 3): 1.0}),
    ]

    values = _bench_boost_trial_values(db_conn, [1, 2, 3], event=10, scenario_draw=scenario_draw)

    assert list(values) == [9.0, 1.0]  # bench is just player 3 in both trials


def test_bench_boost_trial_values_picks_a_different_bench_per_event(db_conn, monkeypatch):
    """Closes CLAUDE.md's "chip selection is event-invariant" limitation for
    the bench-boost side: _candidates must actually be called with `event`
    (threading through to expected_points()'s from_event), not just accept
    the parameter and ignore it. Here player 3 has the better fixture at
    GW10 (so player 2 is benched) and player 2 has the better fixture at
    GW20 (so player 3 is benched) - real pick_starting_xi (unmocked) must
    follow that switch."""
    _seed_squad_for_bench_boost(db_conn)
    # squad_max_play=1 for FWD (unlike the shared helper's 3) so a real bench
    # split actually occurs under pick_starting_xi's real constraint logic -
    # with only 3 total players and FWD max=3, nobody would ever be benched.
    db_conn.execute("UPDATE element_types SET squad_max_play=1 WHERE id=4")
    db_conn.commit()
    import fpl_agent.optimization.chips as chips_mod
    from fpl_agent.optimization.squad import PlayerCandidate

    def fake_candidates(conn, squad_ids, event=None):
        p2_xp, p3_xp = (4.0, 9.0) if event == 10 else (9.0, 4.0)
        xp_by_id = {1: 5.0, 2: p2_xp, 3: p3_xp}
        for pid in squad_ids:
            yield PlayerCandidate(
                player_id=pid, web_name=f"p{pid}", position="GKP" if pid == 1 else "FWD",
                team_id=1, team_short="TMA", price_tenths=0, xp=xp_by_id[pid],
                median=xp_by_id[pid], floor=xp_by_id[pid], ceiling=xp_by_id[pid],
                confidence="HIGH", expected_minutes=90.0,
            )

    monkeypatch.setattr(chips_mod, "_candidates", fake_candidates)

    scenario_draw = [ScenarioOutcome(trial_index=0, points_by_event_player={(10, 2): 6.0, (20, 3): 6.0})]

    gw10_values = _bench_boost_trial_values(db_conn, [1, 2, 3], event=10, scenario_draw=scenario_draw)
    gw20_values = _bench_boost_trial_values(db_conn, [1, 2, 3], event=20, scenario_draw=scenario_draw)

    assert list(gw10_values) == [6.0]  # player 2 (weaker at GW10) is benched, scores its real GW10 points
    assert list(gw20_values) == [6.0]  # player 3 (weaker at GW20) is benched, scores its real GW20 points


def test_triple_captain_trial_values_reads_best_captain_points(db_conn, monkeypatch):
    _seed_squad_for_bench_boost(db_conn)
    import fpl_agent.optimization.chips as chips_mod
    from fpl_agent.optimization.captaincy import CaptainOption

    monkeypatch.setattr(
        chips_mod, "evaluate_captaincy",
        lambda conn, squad_ids, event=None: [CaptainOption(player_id=2, web_name="FWD_starter", position="FWD", floor=1, median=5, ceiling=9, confidence="HIGH", expected_minutes=90, is_penalty_taker=False, opponent_short=None, is_home=None, selected_by_percent=None, effective_ownership_percent=None, eo_source="unavailable")],
    )

    scenario_draw = [
        ScenarioOutcome(trial_index=0, points_by_event_player={(10, 2): 12.0}),
        ScenarioOutcome(trial_index=1, points_by_event_player={(10, 2): 3.0}),
    ]

    values = _triple_captain_trial_values(db_conn, [1, 2, 3], event=10, scenario_draw=scenario_draw)
    assert list(values) == [12.0, 3.0]


def test_triple_captain_trial_values_picks_a_different_captain_per_event(db_conn, monkeypatch):
    """Closes CLAUDE.md's "chip selection is event-invariant" limitation:
    the captain evaluated must actually change when `event` changes, not
    just be accepted as a parameter and ignored. evaluate_captaincy here
    returns a genuinely different top pick depending on which event it's
    asked about (player 2 has the better fixture at GW10, player 3 at
    GW20) - _triple_captain_trial_values must follow that per-event switch
    and read the RIGHT player's scenario points each time."""
    _seed_squad_for_bench_boost(db_conn)
    import fpl_agent.optimization.chips as chips_mod
    from fpl_agent.optimization.captaincy import CaptainOption

    def fake_evaluate_captaincy(conn, squad_ids, event=None):
        best_id = 2 if event == 10 else 3
        return [CaptainOption(player_id=best_id, web_name=f"p{best_id}", position="FWD", floor=1, median=5, ceiling=9, confidence="HIGH", expected_minutes=90, is_penalty_taker=False, opponent_short=None, is_home=None, selected_by_percent=None, effective_ownership_percent=None, eo_source="unavailable")]

    monkeypatch.setattr(chips_mod, "evaluate_captaincy", fake_evaluate_captaincy)

    scenario_draw = [
        ScenarioOutcome(trial_index=0, points_by_event_player={(10, 2): 12.0, (20, 3): 8.0}),
        ScenarioOutcome(trial_index=1, points_by_event_player={(10, 2): 3.0, (20, 3): 6.0}),
    ]

    gw10_values = _triple_captain_trial_values(db_conn, [1, 2, 3], event=10, scenario_draw=scenario_draw)
    gw20_values = _triple_captain_trial_values(db_conn, [1, 2, 3], event=20, scenario_draw=scenario_draw)

    assert list(gw10_values) == [12.0, 3.0]  # player 2's real GW10 points
    assert list(gw20_values) == [8.0, 6.0]  # player 3's real GW20 points - a genuinely different captain


from fpl_agent.optimization.chips import ChipWindow, schedule_chips
from fpl_agent.optimization.transfers import TransferSequence, TransferSequenceStep


def test_schedule_chips_picks_the_higher_value_window(db_conn, monkeypatch):
    import fpl_agent.optimization.chips as chips_mod

    trajectory = TransferSequence(
        steps=(
            TransferSequenceStep(event=10, player_out_id=None, player_out_name=None, player_in_id=None, player_in_name=None, uses_hit=False),
            TransferSequenceStep(event=11, player_out_id=None, player_out_name=None, player_in_id=None, player_in_name=None, uses_hit=False),
        ),
        final_squad_ids=(1, 2, 3), final_free_transfers=1, final_bank_tenths=0,
        total_net_ev=0.0, tiebreak_adjustment=0.0,
    )
    windows = [ChipWindow(name="bboost", number=1, start_event=10, stop_event=19, chip_type="team", eligible_now=True)]

    def fake_bench_boost(conn, squad_ids, event, scenario_draw):
        import numpy as np
        return np.array([10.0, 10.0]) if event == 10 else np.array([2.0, 2.0])

    monkeypatch.setattr(chips_mod, "_bench_boost_trial_values", fake_bench_boost)

    scenario_draw = [object(), object()]  # opaque - the fake value fn ignores it
    schedule = schedule_chips(db_conn, initial_squad_ids=[1, 2, 3], squad_trajectory=trajectory, chip_windows=windows, scenario_draw=scenario_draw)

    assert len(schedule.baseline_schedule) == 1
    assert schedule.baseline_schedule[0].event == 10  # median 10.0 beats median 2.0 at GW11
    assert schedule.baseline_schedule[0].chip_name == "bboost"
    assert schedule.total_expected_value == 10.0
    assert schedule.advisory_hit_recommendations == ()

    # P1 item (2026-08-26 GW1-postmortem audit) - "chip-strategy explanation":
    # the real chosen GW10 (+10.0) vs the real runner-up GW11 (+2.0), built
    # from the DP's own already-computed per-event medians.
    assert len(schedule.explanations) == 1
    exp = schedule.explanations[0]
    assert exp.event == 10 and exp.chip_name == "bboost"
    assert exp.expected_value == 10.0
    assert exp.best_alternative_event == 11
    assert exp.best_alternative_value == 2.0
    assert exp.opportunity_cost == 8.0
    assert exp.confidence == "low"


def test_schedule_chips_explanation_has_no_real_alternative_when_only_one_event_is_eligible(db_conn, monkeypatch):
    """Honest absence, not a fabricated comparison, when the chip's own real
    window only ever covers one real eligible event in the sampled horizon."""
    import fpl_agent.optimization.chips as chips_mod

    trajectory = TransferSequence(
        steps=(TransferSequenceStep(event=10, player_out_id=None, player_out_name=None, player_in_id=None, player_in_name=None, uses_hit=False),),
        final_squad_ids=(1, 2, 3), final_free_transfers=1, final_bank_tenths=0,
        total_net_ev=0.0, tiebreak_adjustment=0.0,
    )
    windows = [ChipWindow(name="bboost", number=1, start_event=10, stop_event=10, chip_type="team", eligible_now=True)]

    def fake_bench_boost(conn, squad_ids, event, scenario_draw):
        import numpy as np
        return np.array([10.0, 10.0])
    monkeypatch.setattr(chips_mod, "_bench_boost_trial_values", fake_bench_boost)

    schedule = schedule_chips(db_conn, initial_squad_ids=[1, 2, 3], squad_trajectory=trajectory, chip_windows=windows, scenario_draw=[object(), object()])

    assert len(schedule.explanations) == 1
    exp = schedule.explanations[0]
    assert exp.best_alternative_event is None
    assert exp.best_alternative_value is None
    assert exp.opportunity_cost is None


from fpl_agent.optimization.transfers import TransferCandidate


def test_advisory_hit_recommendation_can_beat_baseline(db_conn, monkeypatch):
    import fpl_agent.optimization.chips as chips_mod

    trajectory = TransferSequence(
        steps=(TransferSequenceStep(event=10, player_out_id=None, player_out_name=None, player_in_id=None, player_in_name=None, uses_hit=False),),
        final_squad_ids=(1, 2), final_free_transfers=1, final_bank_tenths=0,
        total_net_ev=0.0, tiebreak_adjustment=0.0,
    )
    windows = [ChipWindow(name="bboost", number=1, start_event=10, stop_event=19, chip_type="team", eligible_now=True)]

    def fake_bench_boost(conn, squad_ids, event, scenario_draw):
        import numpy as np
        # A hypothetical squad containing player 99 (the hit target) scores much
        # higher than the baseline [1, 2] squad - proves the advisory path is
        # actually reachable, not dead code the test suite never exercises.
        return np.array([20.0, 20.0]) if 99 in squad_ids else np.array([3.0, 3.0])

    monkeypatch.setattr(chips_mod, "_bench_boost_trial_values", fake_bench_boost)
    monkeypatch.setattr(
        chips_mod, "best_transfer_for_player",
        lambda conn, player_out_id, squad_ids, bank_tenths, is_hit, n_gw=1, top_n=1, from_event=None, cache=None: [
            TransferCandidate(
                player_out_id=player_out_id, player_out_name="Out", player_in_id=99, player_in_name="In",
                price_delta_tenths=0, ev_1gw=0, ev_3gw=0, ev_5gw=0, net_ev_1gw=0, net_ev_3gw=0, net_ev_5gw=0, uses_hit=True,
            )
        ],
    )

    schedule = schedule_chips(db_conn, initial_squad_ids=[1, 2], squad_trajectory=trajectory, chip_windows=windows, scenario_draw=[object(), object()])

    assert schedule.baseline_schedule[0].expected_marginal_value == 3.0
    assert len(schedule.advisory_hit_recommendations) == 1
    rec = schedule.advisory_hit_recommendations[0]
    assert rec.player_in_id == 99
    assert rec.advisory_expected_marginal_value == 20.0 - 4.0  # hit cost
    assert rec.delta > 0


def test_schedule_chips_never_schedules_an_already_used_chip(db_conn, monkeypatch):
    """used_chip_names removes a window from the DP state space entirely - a chip
    already played this season can't be scheduled again no matter how well it
    scores. Deliberately makes the excluded chip the higher-value one, so a filter
    that silently did nothing would show up as bboost still winning."""
    import fpl_agent.optimization.chips as chips_mod

    trajectory = TransferSequence(
        steps=(TransferSequenceStep(event=10, player_out_id=None, player_out_name=None, player_in_id=None, player_in_name=None, uses_hit=False),),
        final_squad_ids=(1, 2, 3), final_free_transfers=1, final_bank_tenths=0,
        total_net_ev=0.0, tiebreak_adjustment=0.0,
    )
    windows = [
        ChipWindow(name="bboost", number=1, start_event=10, stop_event=19, chip_type="team", eligible_now=True),
        ChipWindow(name="3xc", number=1, start_event=10, stop_event=19, chip_type="team", eligible_now=True),
    ]
    monkeypatch.setattr(chips_mod, "_bench_boost_trial_values", lambda conn, squad_ids, event, scenario_draw: np.array([50.0, 50.0]))
    monkeypatch.setattr(chips_mod, "_triple_captain_trial_values", lambda conn, squad_ids, event, scenario_draw: np.array([7.0, 7.0]))
    monkeypatch.setattr(chips_mod, "best_transfer_for_player", lambda *a, **k: [])

    scenario_draw = [object(), object()]
    schedule = schedule_chips(
        db_conn, initial_squad_ids=[1, 2, 3], squad_trajectory=trajectory, chip_windows=windows,
        scenario_draw=scenario_draw, used_chip_names={"bboost"},
    )

    scheduled_names = {e.chip_name for e in schedule.baseline_schedule}
    assert "bboost" not in scheduled_names
    assert scheduled_names == {"3xc"}
    assert schedule.total_expected_value == 7.0


def test_wildcard_trial_values_scores_rebuilt_members_outside_the_sampled_squad(db_conn, monkeypatch):
    """Regression guard for the whole-branch review's Critical finding, at the
    chips.py end: the rebuilt squad comes from the FULL player pool and is generally
    disjoint from squad_ids, so its members' per-trial points must come from the
    scenario draw for the wildcard/freehit comparison to mean anything. Before the
    fix at the season-sim call site those players were never sampled, so _total()
    scored the whole rebuilt squad as 0.0 and wildcard/freehit marginal value was
    provably <= 0 on every trial - the chip could never be scheduled. Exercises the
    real (unmocked) _wildcard_trial_values arithmetic, which had no coverage at all.
    """
    import fpl_agent.optimization.chips as chips_mod
    from types import SimpleNamespace

    chips_mod._squad_rebuild_cache.clear()
    # Rebuilt squad is entirely disjoint from the held squad [1, 2] - exactly the
    # case optimise_squad produces in real use, since it rebuilds from scratch.
    monkeypatch.setattr(
        chips_mod, "optimise_squad",
        lambda conn, n_gw: SimpleNamespace(squad=[SimpleNamespace(player_id=3), SimpleNamespace(player_id=4)]),
    )

    # One event in the horizon, held squad worth 4.0, rebuilt squad worth 20.0.
    scenario_draw = [
        ScenarioOutcome(trial_index=0, points_by_event_player={(10, 1): 1.0, (10, 2): 3.0, (10, 3): 12.0, (10, 4): 8.0}),
        ScenarioOutcome(trial_index=1, points_by_event_player={(10, 1): 0.0, (10, 2): 0.0, (10, 3): 6.0, (10, 4): 2.0}),
    ]

    values = chips_mod._wildcard_trial_values(db_conn, [1, 2], event=10, horizon_gw=1, scenario_draw=scenario_draw)

    assert list(values) == [16.0, 8.0]  # (12+8)-(1+3), (6+2)-(0+0)
    assert float(np.median(values)) > 0.0  # the DP can actually schedule a wildcard now
    chips_mod._squad_rebuild_cache.clear()


def test_wildcard_trial_values_bounds_the_window_regardless_of_dp_horizon(db_conn, monkeypatch):
    """Real bug found (flagged, not fixed) 2026-08-27's "audit against real GW2
    expert reasoning" session, fixed here: _wildcard_trial_values used to sum the
    rebuilt-vs-current gap over the CALLER's full DP horizon_gw (e.g. 19 for a
    --horizon 19 season-sim call) - crediting a one-time rebuilt squad with an
    ever-growing, uncontested advantage against a squad that structurally never
    receives a single transfer for the whole horizon. Bounded to
    _WILDCARD_TRIAL_WINDOW_GW (5, matching wildcard_value's own bounded n_gw=5
    default) regardless of how large horizon_gw is. Two things pinned directly,
    not just the total: optimise_squad is solved with n_gw=5 (not 19), and events
    beyond the 5-GW window (e.g. event 12, 10+2) never contribute to the gap even
    though they're present in scenario_draw with a huge, deliberately-suspicious
    value that would blow up the total if the (pre-fix) unbounded window were
    still in effect."""
    import fpl_agent.optimization.chips as chips_mod
    from types import SimpleNamespace

    chips_mod._squad_rebuild_cache.clear()
    n_gw_calls = []

    def recording_optimise(conn, n_gw):
        n_gw_calls.append(n_gw)
        return SimpleNamespace(squad=[SimpleNamespace(player_id=3)])

    monkeypatch.setattr(chips_mod, "optimise_squad", recording_optimise)

    scenario_draw = [
        ScenarioOutcome(trial_index=0, points_by_event_player={
            (10, 1): 1.0, (10, 3): 5.0,  # within the bounded 5-GW window (events 10-14)
            (12, 1): 1000.0, (12, 3): 1000.0,  # inside the caller's 19-GW horizon but outside the bounded window
        }),
    ]

    values = chips_mod._wildcard_trial_values(db_conn, [1], event=10, horizon_gw=19, scenario_draw=scenario_draw)

    assert n_gw_calls == [5]  # bounded, not the caller's own horizon_gw=19
    assert list(values) == [4.0]  # (5.0) - (1.0), event 12's huge values never entered the sum
    chips_mod._squad_rebuild_cache.clear()


def test_cached_optimise_squad_solves_once_per_n_gw(db_conn, monkeypatch):
    import fpl_agent.optimization.chips as chips_mod
    from types import SimpleNamespace

    chips_mod._squad_rebuild_cache.clear()
    calls = []

    def counting_optimise(conn, n_gw):
        calls.append(n_gw)
        return SimpleNamespace(squad=[])

    monkeypatch.setattr(chips_mod, "optimise_squad", counting_optimise)

    first = chips_mod._cached_optimise_squad(db_conn, 5)
    second = chips_mod._cached_optimise_squad(db_conn, 5)
    chips_mod._cached_optimise_squad(db_conn, 1)

    assert first is second
    assert calls == [5, 1]  # the repeat 5-GW solve came from the memo, not a re-solve
    chips_mod._squad_rebuild_cache.clear()
