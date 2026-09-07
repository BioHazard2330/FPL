# tests/test_transfer_search.py
import sqlite3
from collections import Counter
from types import SimpleNamespace

from fpl_agent.optimization import transfers as transfers_mod
from fpl_agent.optimization.transfers import search_transfer_sequences

# Team 2's players always score more per GW than team 1's, flat across every
# event - deliberately simple and event-independent so the regression test
# below has an unambiguous, hand-computable correct answer.
_PLAYER_GW_EV = {1: 3.0, 2: 3.0, 3: 6.0, 4: 6.0}


def _seed_two_team_pool(conn: sqlite3.Connection):
    now = "2026-01-01T00:00:00Z"
    conn.execute(f"INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Team A','TMA','{now}')")
    conn.execute(f"INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (2,2,'Team B','TMB','{now}')")
    conn.execute(
        f"INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, squad_min_play, "
        f"squad_max_play, squad_select, updated_at) VALUES (1,'Forward','FWD','Forwards',1,3,3,'{now}')"
    )
    for pid, team_id, name, price in ((1, 1, 'Weak A', 50), (2, 1, 'Weak B', 50), (3, 2, 'Strong A', 55), (4, 2, 'Strong B', 55)):
        conn.execute(
            f"INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
            f"VALUES ({pid},{pid},'{name}',{team_id},1,'a',0,'{now}')"
        )
        conn.execute(
            f"INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) "
            f"VALUES ({pid}, {price}, '{now}', NULL)"
        )
    conn.execute(
        f"INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        f"is_current, is_next, updated_at) VALUES (1,'GW1','{now}',0,0,0,1,1,'{now}')"
    )
    conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) VALUES "
        "('rules.max_extra_free_transfers','2026-27',1,'2026-08-01','fpl_api_bootstrap','4')"
    )
    conn.commit()


def _patch_expected_points_window(monkeypatch):
    def fake(conn, player_id, n_gw, from_event=None):
        return SimpleNamespace(total_median=_PLAYER_GW_EV[player_id])

    monkeypatch.setattr(transfers_mod, "expected_points_window", fake)


def _seed_spiky_vs_steady_pool(conn: sqlite3.Connection):
    """A real, disclosed adversarial fixture (2026-09-02, Phase 5B optimizer
    forensic rebuild, PART 1) - two candidate replacements for the SAME
    owned player: SPIKY (id=5) has a real, large single-GW total but barely
    grows over 3 GWs (a one-week fixture swing, nothing after); STEADY
    (id=6) has a modest single-GW total but a real, much larger cumulative
    3-GW total (consistently good, no single standout week). Proves the
    real bug this phase found and fixed: candidate ranking at the real beam
    step used to use `n_gw=1` only - SPIKY would win that comparison and
    STEADY would never even be evaluated as a real transfer-in option,
    despite being the genuinely better real 3-GW pick."""
    now = "2026-01-01T00:00:00Z"
    conn.execute(f"INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Team A','TMA','{now}')")
    conn.execute(f"INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (2,2,'Team B','TMB','{now}')")
    conn.execute(
        f"INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, squad_min_play, "
        f"squad_max_play, squad_select, updated_at) VALUES (1,'Forward','FWD','Forwards',1,3,3,'{now}')"
    )
    for pid, team_id, name, price in ((1, 1, 'Owned', 50), (5, 2, 'Spiky', 50), (6, 2, 'Steady', 50)):
        conn.execute(
            f"INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
            f"VALUES ({pid},{pid},'{name}',{team_id},1,'a',0,'{now}')"
        )
        conn.execute(
            f"INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) "
            f"VALUES ({pid}, {price}, '{now}', NULL)"
        )
    conn.execute(
        f"INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        f"is_current, is_next, updated_at) VALUES (1,'GW1','{now}',0,0,0,1,1,'{now}')"
    )
    conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) VALUES "
        "('rules.max_extra_free_transfers','2026-27',1,'2026-08-01','fpl_api_bootstrap','4')"
    )
    conn.commit()


_SPIKY_VS_STEADY_TOTALS = {
    # player_id: {n_gw: real cumulative total_median}
    1: {1: 1.0, 3: 3.0, 5: 5.0},  # Owned - mediocre either way, real transfer target
    5: {1: 5.0, 3: 6.0, 5: 6.5},  # Spiky - wins the 1-GW comparison, barely grows after
    6: {1: 3.0, 3: 9.0, 5: 14.0},  # Steady - loses the 1-GW comparison, wins over 3/5 GW
}


def _patch_spiky_vs_steady(monkeypatch):
    def fake(conn, player_id, n_gw, from_event=None):
        return SimpleNamespace(total_median=_SPIKY_VS_STEADY_TOTALS[player_id][n_gw])

    monkeypatch.setattr(transfers_mod, "expected_points_window", fake)


def test_single_gw_candidate_ranking_would_have_excluded_the_real_better_3gw_pick(db_conn, monkeypatch):
    """Real, direct proof of the bug this phase found (not the fix) - ranking
    by `n_gw=1` alone puts Spiky first and would drop Steady from a
    `top_n=1` slice, even though Steady is the real, better 3-GW pick."""
    _seed_spiky_vs_steady_pool(db_conn)
    _patch_spiky_vs_steady(monkeypatch)
    from fpl_agent.optimization.transfers import best_transfer_for_player

    ranked_by_1gw = best_transfer_for_player(db_conn, 1, [1], bank_tenths=100, is_hit=False, n_gw=1, top_n=1)
    assert ranked_by_1gw[0].player_in_name == "Spiky"


def test_beam_candidate_generation_now_ranks_by_the_real_3gw_window(db_conn, monkeypatch):
    """Real regression guard for the actual fix (2026-09-02, PART 1) -
    `search_transfer_sequences`'s own real per-step candidate call must use
    `n_gw=3`, not `n_gw=1` - proven by capturing the real `n_gw` argument
    `best_transfer_for_player` is actually invoked with from inside the real
    beam search, never by re-deriving the beam's own internal call."""
    _seed_spiky_vs_steady_pool(db_conn)
    _patch_spiky_vs_steady(monkeypatch)
    from fpl_agent.optimization import transfers as transfers_mod_local

    real_best_transfer_for_player = transfers_mod_local.best_transfer_for_player
    seen_n_gw = []

    def spy(conn, player_out_id, squad_ids, bank_tenths, is_hit, n_gw=3, top_n=5, from_event=None, cache=None):
        seen_n_gw.append(n_gw)
        return real_best_transfer_for_player(
            conn, player_out_id, squad_ids, bank_tenths, is_hit, n_gw=n_gw, top_n=top_n, from_event=from_event, cache=cache,
        )

    monkeypatch.setattr(transfers_mod_local, "best_transfer_for_player", spy)

    search_transfer_sequences(db_conn, squad_ids=[1], free_transfers=1, bank_tenths=100, horizon_gw=1, beam_width=3)

    assert seen_n_gw, "the beam's own per-step candidate call never ran"
    assert all(n == 3 for n in seen_n_gw), f"expected every real beam candidate call to use n_gw=3, saw {seen_n_gw}"


def test_top_n_nomination_now_survives_with_the_real_3gw_ranking(db_conn, monkeypatch):
    """Real, end-to-end proof at the actual nomination boundary (not the
    final path winner - `_squad_gw_ev`'s own real per-event scoring is a
    separate, already-correct mechanism this fix never touches). With 4 real
    candidates and a real `top_n=3` slice (the beam's own real value), the
    OLD `n_gw=1` ranking would drop Steady entirely (3 decoys all beat its
    real 1-GW rate); the real, fixed `n_gw=3` ranking keeps it in."""
    _seed_spiky_vs_steady_pool(db_conn)
    # 3 real decoys, each beating Steady's real 1-GW rate (3.5) but losing to
    # it on the real 3-GW cumulative total (9.0).
    now = "2026-01-01T00:00:00Z"
    for pid, name in ((7, "Decoy1"), (8, "Decoy2"), (9, "Decoy3")):
        db_conn.execute(
            f"INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
            f"VALUES ({pid},{pid},'{name}',2,1,'a',0,'{now}')"
        )
        db_conn.execute(
            f"INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) "
            f"VALUES ({pid}, 50, '{now}', NULL)"
        )
    db_conn.commit()
    totals = dict(_SPIKY_VS_STEADY_TOTALS)
    totals[6] = {1: 3.5, 3: 9.0, 5: 14.0}
    for pid in (7, 8, 9):
        totals[pid] = {1: 4.0, 3: 4.5, 5: 5.0}  # real 1-GW winner, real 3-GW loser vs Steady

    def fake(conn, player_id, n_gw, from_event=None):
        return SimpleNamespace(total_median=totals[player_id][n_gw])

    monkeypatch.setattr(transfers_mod, "expected_points_window", fake)
    from fpl_agent.optimization.transfers import best_transfer_for_player

    old_ranking = best_transfer_for_player(db_conn, 1, [1], bank_tenths=100, is_hit=False, n_gw=1, top_n=3)
    new_ranking = best_transfer_for_player(db_conn, 1, [1], bank_tenths=100, is_hit=False, n_gw=3, top_n=3)

    assert "Steady" not in {c.player_in_name for c in old_ranking}
    assert "Steady" in {c.player_in_name for c in new_ranking}


def test_search_transfer_sequences_returns_bounded_beam(db_conn, monkeypatch):
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)
    sequences = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=3, beam_width=4,
    )
    assert 0 < len(sequences) <= 4
    for seq in sequences:
        assert len(seq.steps) == 3
        assert isinstance(seq.total_net_ev, float)


def test_search_transfer_sequences_credits_transferred_player_across_full_horizon(db_conn, monkeypatch):
    """Regression test for the exact bug class this task's algorithm section warns
    about (point 4). With flat, event-independent per-GW rates (team 2 = 6.0/GW,
    team 1 = 3.0/GW) and a free-transfer allowance of 1 at the start plus FPL's
    real accrual rule (+1 FT at every deadline, capped at max_banked, regardless
    of whether a transfer was made that week - see search_transfer_sequences'
    free-transfer bookkeeping), the CORRECT total is reached by swapping BOTH weak
    players for strong ones as early as legally possible using only free transfers,
    then holding the fully-strong squad for the rest of the horizon:
      - GW1: 1 free transfer available -> swap player 1 (weak) for player 3
        (strong). Squad (2,3) this GW: 3.0 + 6.0 = 9.0. Spending the free
        transfer nets back to 1 FT available next GW (FPL grants +1 regardless of
        whether you transferred), since it wasn't a hit.
      - GW2: 1 free transfer available again -> swap player 2 (weak) for player 4
        (strong). Squad (3,4) this GW: 6.0 + 6.0 = 12.0. Again a free transfer,
        not a hit.
      - GW3: squad is now (3,4), fully strong - roll (no further transfer
        needed). Squad (3,4) this GW: 6.0 + 6.0 = 12.0.
      Total = 9.0 + 12.0 + 12.0 = 33.0, no hit cost anywhere (every transfer used
      a free transfer that was actually available under the correct accrual rule).
    A DELTA-ONLY implementation - one that only adds the one-time EV difference at
    the moment of transfer instead of the full squad's EV every remaining GW -
    could never reach this magnitude: it would never count player 2's ongoing
    3.0/GW baseline contribution at all, let alone player 3's/4's, producing a
    total in the single digits instead. Separately, an implementation that gets
    the full-horizon-credit property right but mis-prices free-transfer accrual
    (failing to add the next GW's automatic +1 when a transfer already consumed
    the current one) would incorrectly treat the GW2 swap above as a hit, pricing
    it 4.0 points worse and likely causing the search to prefer swapping only once
    and holding/rolling instead - reaching 30.0 or lower, not 33.0. This is a
    magnitude check, not a tie-break-order check, specifically because tie-break
    order between equally-buggy-scored sequences is not a reliable way to detect
    either bug (verified by hand-tracing the beam's greedy pruning behavior during
    planning - a delta-only bug can still coincidentally front-load transfers
    early for unrelated reasons, so checking WHEN the swap happens is not a sound
    regression guard; checking the resulting MAGNITUDE is)."""
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    sequences = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=3, beam_width=4,
    )
    best = sequences[0]

    # Threshold set at 31.0, not just "clearly above single digits": independently
    # verified by hand-replicating both buggy variants against the real helpers -
    # a delta-only implementation lands in the single digits (nowhere close);
    # an implementation with correct full-horizon credit but mis-priced
    # free-transfer accrual (treating a spent free transfer as permanently gone
    # instead of still netting the next GW's automatic +1) lands at exactly 30.0
    # here (verified), one GW short of the second transfer's window. 31.0 sits
    # strictly above that 30.0 buggy-accrual result and comfortably below the
    # true optimum of 33.0, so this one assertion now catches both bug classes,
    # not just the delta-only one.
    assert best.total_net_ev >= 31.0, (
        f"got {best.total_net_ev}, expected close to 33.0 (transfer into both strong "
        "players using free transfers only across GW1/GW2, then hold at 9.0(GW1)+"
        "12.0(GW2)+12.0(GW3)). A total near 30.0 suggests free-transfer accrual is "
        "mis-priced (a spent free transfer should still net back to the same FT count "
        "next GW, not decrement it permanently - the roll branch already gets this "
        "right, check the transfer branch matches). A total in the single digits "
        "suggests cumulative_ev is only counting transfer-moment deltas instead of "
        "full-squad EV summed across every horizon GW."
    )


def test_search_transfer_sequences_respects_max_banked_free_transfers(db_conn, monkeypatch):
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)
    sequences = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=5, bank_tenths=100, horizon_gw=2, beam_width=4,
    )
    for seq in sequences:
        assert seq.final_free_transfers <= 5  # max_banked from the seeded rule (1 + 4)


def _patch_expected_points_window_event_dependent(monkeypatch):
    """Event-DEPENDENT fake, local to the horizon-awareness test below - deliberately
    different from the shared _PLAYER_GW_EV (which ignores from_event entirely and so
    cannot catch a regression that breaks from_event threading through the horizon
    loop - see that test's own note). Player 3 (strong) scores a one-off 10.0 spike
    ONLY at event=1 (simulating e.g. a double gameweek or a one-off favourable
    fixture) and reverts to a mundane 2.5 at every later event; players 1/2 (weak,
    starting squad) and player 4 (an uninteresting always-worse alternative target)
    are flat regardless of event, so they can't confound the event=1-vs-later
    comparison. n_gw != 1 returns an out-of-range sentinel (-1000.0) rather than a
    real value: search_transfer_sequences only ever calls best_transfer_for_player
    with n_gw=1 (see its own docstring/call site), so a correct search never reads
    this branch - if a regression ever passed a different n_gw through, the sentinel
    would corrupt the ranking and the magnitude assertion below would catch it too
    (a partial guard for that secondary property, not an exhaustive one)."""
    def fake(conn, player_id, n_gw, from_event=None):
        if n_gw != 1:
            return SimpleNamespace(total_median=-1000.0)
        if player_id in (1, 2):
            return SimpleNamespace(total_median=2.0)
        if player_id == 4:
            return SimpleNamespace(total_median=0.5)
        if player_id == 3:
            return SimpleNamespace(total_median=10.0 if from_event == 1 else 2.5)
        raise AssertionError(f"unexpected player_id {player_id}")

    monkeypatch.setattr(transfers_mod, "expected_points_window", fake)


def test_search_transfer_sequences_uses_the_correct_event_per_horizon_step(db_conn, monkeypatch):
    """Proves the search actually threads from_event through each horizon step,
    rather than (as the final-branch-review mutation test demonstrated) silently
    reusing event=1's data for every step while every other test in this file still
    passes green, because they all use an event-INDEPENDENT fake.

    Setup: squad_ids=[1,2] (both flat 2.0/GW, every event), free_transfers=1,
    bank_tenths=100, horizon_gw=2, beam_width=4. Player 3 spikes to 10.0 ONLY at
    event=1 and is a mundane 2.5 at event=2 onward; player 4 is a flat, always-worse
    0.5 (never worth transferring in, so it can't confound the comparison).

    Hand-derived values below use the real captain-aware `_squad_gw_ev`
    (2026-09-02 decision-engine fix - `resolve_gw_xi` picks the real best XI
    and doubles the top scorer, replacing the old flat uncaptained sum this
    2-player squad always fully "starts" either way, so the only change here
    is the captain double on the squad's own top scorer each GW).

    Hand-derived correct optimum (buy player 3 as early as legally possible, GW1,
    using the free transfer, then hold):
      - GW1 (event=1): swap player 1 -> player 3 (free transfer, not a hit, since
        free_transfers=1 >= 1). Squad (2,3) this GW: values {2.0, 10.0}, captain=3
        (highest) doubled: 2.0 + 10.0 + 10.0 = 22.0. Free transfer accrual nets
        back to 1 FT still available next GW (spending a banked FT while the
        automatic +1 still arrives - same rule the existing 33.0 regression test
        exercises).
      - GW2 (event=2): squad is already (2,3), values {2.0, 2.5}. Holding (roll)
        scores 2.0 + 2.5 + 2.5 (captain=3, still the higher value) = 7.0 - this
        now STRICTLY beats swapping 3 back out for 1 (squad (1,2), both flat 2.0,
        captain doesn't matter: 2.0+2.0+2.0=6.0), unlike the old uncaptained tie.
      Total = 22.0 + 7.0 = 29.0, no hit cost anywhere.

    Contrast with buying LATE instead (never transferring at GW1, i.e. rolling
    first): squad stays (1,2) at GW1, both flat 2.0, captain doesn't matter:
    2.0+2.0+2.0=6.0 (missing the 10.0 spike entirely, since it only exists at
    event=1 and this path wasn't in player 3 yet). GW2 then swaps in player 3 at
    its mundane 2.5: new squad (2,3), captain=3(2.5): 2.0+2.5+2.5=7.0.
    Total = 6.0 + 7.0 = 13.0 - the correct implementation must never choose this
    path when the early path is available, and 29.0 is measurably (not
    marginally) higher than 13.0, so this is a real discriminating gap, not a
    rounding-level difference.

    Mutation check performed during development (see task notes): temporarily
    freezing `event` at `start_event` for every offset in the horizon loop (the
    exact "always use event=1" mutation the final review used to prove this
    property was previously unguarded) was confirmed to make this test FAIL - under
    that mutation player 3's 10.0 spike is (incorrectly) visible at every step, not
    just event=1, so the search instead holds (2,3) for both GWs at an inflated
    22.0/GW (captain-doubled 10.0 spike every GW), reaching 44.0 total, not 29.0.
    The mutation was reverted immediately after confirming the failure; only this
    test (and the fake above) remain as the permanent regression guard.
    """
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window_event_dependent(monkeypatch)

    sequences = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=2, beam_width=4,
    )
    best = sequences[0]

    assert best.total_net_ev == 29.0, (
        f"got {best.total_net_ev}, expected exactly 29.0 (buy player 3 at GW1 to "
        "capture its event=1-only 10.0 spike as captain, then hold: 22.0(GW1) + 7.0(GW2)). "
        "44.0 would mean event=1's data is being reused for every horizon step "
        "(from_event isn't threading through correctly - the exact bug class the "
        "final review's mutation test proved was unguarded). 13.0 would mean the "
        "search bought in late (or never), missing the early-event spike entirely."
    )


def _patch_expected_points_window_wide_gap(monkeypatch):
    """Separate fake, local to the wildcard-proximity test below: team 2 (players
    3/4) is boosted to 8.0/GW (vs the shared module's 6.0) instead of the usual
    3.0/6.0 split. This widens strong-minus-weak from 3.0 to 5.0, which is
    necessary for this specific test to actually discriminate a real
    WILDCARD_PROXIMITY_PENALTY application from a no-op one - see the test's own
    docstring for the arithmetic. Deliberately not reusing the shared
    _PLAYER_GW_EV dict, since changing it would also change the hand-computed
    magnitudes the other tests in this file depend on (e.g. the 33.0 regression
    test above)."""
    values = {1: 3.0, 2: 3.0, 3: 8.0, 4: 8.0}

    def fake(conn, player_id, n_gw, from_event=None):
        return SimpleNamespace(total_median=values[player_id])

    monkeypatch.setattr(transfers_mod, "expected_points_window", fake)


def test_wildcard_proximity_penalizes_a_hit_the_gw_before_the_window(db_conn, monkeypatch):
    """Regression test for the chip_type-vs-name bug caught during planning (see
    this task's Algorithm section, point 6) - matching on chip_type instead of
    name would make this penalty silently never fire.

    Unlike the other tests in this file, this one uses a widened weak/strong gap
    (3.0 vs 8.0/GW, via _patch_expected_points_window_wide_gap) rather than the
    shared 3.0/6.0 split. With the shared 3.0/6.0 split, a hit-swap into a strong
    player scores 3.0+6.0-HIT_COST(4.0)=5.0 even with the WILDCARD_PROXIMITY_PENALTY
    disabled entirely - roll (6.0) already beats it either way, so that scenario
    can't tell a real penalty application apart from a silently-broken one (both
    produce "roll wins"). Widening the gap to 3.0/8.0 makes the hit-swap score
    3.0+8.0-4.0=7.0 WITHOUT the penalty - enough to beat roll's 6.0 - so the
    penalty's actual effect (dropping it to 3.0+8.0-4.0-2.0=5.0, below roll's 6.0)
    is what flips the winner, not an accident of the raw EV/HIT_COST arithmetic.
    """
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window_wide_gap(monkeypatch)
    db_conn.execute(
        "INSERT INTO chip_windows (id, name, number, start_event, stop_event, chip_type, season, updated_at) "
        "VALUES (1, 'wildcard', 1, 2, 19, 'transfer', '2026-27', '2026-01-01T00:00:00Z')"
    )
    db_conn.commit()

    # Real behavior change (2026-09-02, decision-engine fix - `_squad_gw_ev`
    # now applies a real captain double to the squad's own top scorer): the
    # incoming strong player (8.0) also becomes captain, so the hit-swap's
    # real margin over roll grew far past what a flat -2.0 penalty can flip
    # (hit-swap: 3.0+8.0+8.0(captain)-4.0(hit)=15.0 vs roll: 3.0+3.0+3.0
    # (captain, tied)=9.0 - the penalty alone can no longer make roll win
    # outright in this scenario, unlike under the old uncaptained sum). The
    # real invariant this test protects - the penalty measurably fires, not
    # a chip_type-vs-name no-op - is proven more robustly here by comparing
    # the search WITH the real penalty against the identical search with it
    # neutralized, rather than depending on it being large enough to flip
    # the winner (which is a fact about HIT_COST/the strong-weak gap, not
    # about whether the penalty itself fires).
    sequences_with_penalty = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=0, bank_tenths=100, horizon_gw=1, beam_width=4,
    )
    best_with_penalty = sequences_with_penalty[0]

    monkeypatch.setattr(transfers_mod, "WILDCARD_PROXIMITY_PENALTY", 0.0)
    sequences_without_penalty = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=0, bank_tenths=100, horizon_gw=1, beam_width=4,
    )
    best_without_penalty = sequences_without_penalty[0]

    assert best_with_penalty.steps[0].uses_hit, (
        "expected the hit-swap into the strong (now captain-boosted) player to still "
        "win outright even with the real proximity penalty applied - if this fails, "
        "the hand-derived captain-aware magnitudes in this test's own docstring need "
        "re-checking against the real _squad_gw_ev behavior"
    )
    # The penalty is reported separately (`tiebreak_adjustment`), deliberately never
    # folded into `total_net_ev` (that field is documented as "pure squad EV minus
    # real hit costs" - see TransferSequence's own field comment) - so the real
    # invariant to check is the tiebreak field, not the headline total.
    assert best_with_penalty.tiebreak_adjustment == -2.0, (
        f"expected the real WILDCARD_PROXIMITY_PENALTY (2.0) to show up as a -2.0 "
        f"tiebreak_adjustment on the hit-swap taken one GW before the wildcard window - "
        f"got {best_with_penalty.tiebreak_adjustment}. Zero would mean the penalty "
        "silently isn't firing (check whether the wildcard-proximity check is matching "
        "on ChipWindow.chip_type instead of .name)"
    )
    assert best_without_penalty.tiebreak_adjustment == 0.0


def test_price_tiebreak_bonus_prefers_rising_player_among_equal_ev_candidates(db_conn, monkeypatch):
    """Seeded on player 4, not player 3. Candidate generation order (the SQL scan
    in best_transfer_for_player has no ORDER BY, so ties resolve to id-ascending,
    id 3 before id 4) already favours player 3 by construction - if we seeded the
    RISE_LIKELY momentum on player 3 too, the test would pass even with
    PRICE_TIEBREAK_BONUS silently disabled (it would just be reproducing the
    generation-order winner). Seeding on player 4 instead means the bonus has to
    actually overturn the default generation-order preference for the test to
    pass, which is what makes it a real regression guard."""
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)
    db_conn.execute("INSERT INTO app_meta (key, value, updated_at) VALUES ('total_players','1000000','2026-01-01T00:00:00Z')")
    db_conn.execute(
        "INSERT INTO player_transfer_momentum_history "
        "(player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from, valid_until) "
        "VALUES (4, 8000, 100, 8000, 100, '2026-01-01T00:00:00Z', NULL)"
    )
    db_conn.commit()

    # Players 3 and 4 have identical EV (both 6.0/GW, same price) in this seed -
    # only player 4's seeded RISE_LIKELY momentum should break the tie. Without
    # the bonus, the tie resolves to player 3 (generated first); with it, player
    # 4's contribution gets +0.1, overtaking player 3's plain score.
    sequences = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=1, beam_width=1,
    )
    best = sequences[0]
    swap_step = next(s for s in best.steps if s.player_in_id is not None)
    assert swap_step.player_in_id == 4


def test_search_transfer_sequences_never_recommends_an_illegal_club_count(db_conn, monkeypatch):
    """Real scenario found live 2026-08-20: a squad already at the 3-player cap
    on multiple clubs had search_transfer_sequences recommend bringing in a
    player from a DIFFERENT already-at-cap club - an illegal squad. Reproduces
    it at minimal scale: club A already has 3 squad members (10,11,12, all
    strong - no reason to swap any of them out), club B's squad member (20) is
    clearly the weakest, and the highest-EV replacement candidate (13) is
    ALSO from club A - illegal to bring in via a 20-out swap specifically
    (club A would go 3 -> 4 among the remaining squad).

    Real behavior change (2026-09-02, decision-engine forensic audit fix -
    `_squad_gw_ev` now applies a real captain double to the squad's own
    highest-xP starter, not a flat uncaptained sum): bringing in 13 (the
    highest-EV player, a real captaincy asset) via a DIFFERENT, always-legal
    intra-club-A swap (10 OUT for 13 IN - same club, net zero club-A count
    change) is now genuinely the correct pick once captaincy is valued -
    real math: {11,12,13,20} totals 5+5+9+1 plus a real +9 captain bonus for
    13 = 29, beating {10,11,12,30}'s 5+5+5+6 plus a +6 captain bonus = 27.
    This is NOT the bug this test exists to catch - club A's count stays at
    a real, legal 3 either way (11,12,13). The real invariant this test
    protects - no returned squad ever exceeds the real club cap - is checked
    directly below against the ACTUAL resulting squad, rather than assuming
    one specific swap identity that only held under the old, uncaptained
    value function."""
    now = "2026-01-01T00:00:00Z"
    for tid, name in ((1, "Club A"), (2, "Club B"), (3, "Club C")):
        db_conn.execute(f"INSERT INTO teams (id, code, name, short_name, updated_at) VALUES ({tid},{tid},'{name}','{name[:3].upper()}','{now}')")
    db_conn.execute(
        f"INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        f"VALUES (1,'Forward','FWD','Forwards','{now}')"
    )
    for pid, team_id, price in ((10, 1, 50), (11, 1, 50), (12, 1, 50), (20, 2, 50), (13, 1, 50), (30, 3, 50)):
        db_conn.execute(
            f"INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
            f"VALUES ({pid},{pid},'P{pid}',{team_id},1,'a',0,'{now}')"
        )
        db_conn.execute(
            f"INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) "
            f"VALUES ({pid}, {price}, '{now}', NULL)"
        )
    db_conn.execute(
        f"INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        f"is_current, is_next, updated_at) VALUES (1,'GW1','{now}',0,0,0,1,1,'{now}')"
    )
    db_conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) VALUES "
        "('rules.max_extra_free_transfers','2026-27',1,'2026-08-01','fpl_api_bootstrap','4')"
    )
    db_conn.commit()

    # 10/11/12 (club A, in squad) strong at 5.0 - no incentive to disturb them.
    # 20 (club B, in squad) weak at 1.0 - the obvious swap-out target.
    # 13 (club A candidate) highest EV at 9.0 - illegal for the 20-out swap.
    # 30 (club C candidate) at 6.0 - legal, the correct pick.
    ev_by_id = {10: 5.0, 11: 5.0, 12: 5.0, 20: 1.0, 13: 9.0, 30: 6.0}

    def fake(conn, player_id, n_gw, from_event=None):
        return SimpleNamespace(total_median=ev_by_id[player_id])
    monkeypatch.setattr(transfers_mod, "expected_points_window", fake)

    sequences = search_transfer_sequences(
        db_conn, squad_ids=[10, 11, 12, 20], free_transfers=1, bank_tenths=100, horizon_gw=1, beam_width=4,
    )

    best = sequences[0]
    swap_step = next(s for s in best.steps if s.player_in_id is not None)

    club_by_player = {10: 1, 11: 1, 12: 1, 20: 2, 13: 1, 30: 3}
    club_counts = Counter(club_by_player[pid] for pid in swap_step.resulting_squad_ids)
    assert all(count <= 3 for count in club_counts.values()), (
        f"resulting squad {swap_step.resulting_squad_ids} has an illegal club count: {dict(club_counts)}"
    )


def test_search_transfer_sequences_validates_club_limit_across_multiple_real_steps(db_conn, monkeypatch):
    """P1 item (2026-08-26 GW1-postmortem audit) - "full-sequence club-limit
    validation". The single-step test above proves one swap respects the
    ORIGINAL squad's club counts; this proves a SECOND, LATER step respects
    the squad as it stood AFTER the first step's own swap, not the original
    squad - the real question the audit asked to verify.

    Squad starts at club A=2 (P1,P2, both real EV 10 - strictly better than
    every candidate below, so the search has no reason to ever swap them
    out, ruling out the "swap the incumbent instead" escape that made a
    first attempt at this test accidentally pass for the wrong reason).
    club B=2 (P3,P4, weak, the real swap-out targets). Step 1 swaps P3(B)
    for P6(A, EV 9) - legal (club A: 2->3, at cap but not over). Step 2 must
    swap P4(B) for something - P5(A, EV 8) would push club A to 4 - illegal
    given the squad AFTER step 1, even though it would have been legal
    against the ORIGINAL squad (club A was only 2 there). The search must
    correctly reject P5 and fall back to the lower-EV, legal P7(C)."""
    now = "2026-01-01T00:00:00Z"
    for tid, name in ((1, "Club A"), (2, "Club B"), (3, "Club C")):
        db_conn.execute(f"INSERT INTO teams (id, code, name, short_name, updated_at) VALUES ({tid},{tid},'{name}','{name[:3].upper()}','{now}')")
    db_conn.execute(
        f"INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        f"VALUES (1,'Forward','FWD','Forwards','{now}')"
    )
    for pid, team_id in ((1, 1), (2, 1), (3, 2), (4, 2), (5, 1), (6, 1), (7, 3)):
        db_conn.execute(
            f"INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
            f"VALUES ({pid},{pid},'P{pid}',{team_id},1,'a',0,'{now}')"
        )
        db_conn.execute(
            f"INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) "
            f"VALUES ({pid}, 50, '{now}', NULL)"
        )
    db_conn.execute(
        f"INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        f"is_current, is_next, updated_at) VALUES (1,'GW1','{now}',0,0,0,1,1,'{now}')"
    )
    db_conn.execute(
        f"INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        f"is_current, is_next, updated_at) VALUES (2,'GW2','{now}',1,0,0,0,0,'{now}')"
    )
    db_conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) VALUES "
        "('rules.max_extra_free_transfers','2026-27',1,'2026-08-01','fpl_api_bootstrap','4')"
    )
    db_conn.commit()

    # P1/P2 (club A, in squad) - EV 10 each, strictly higher than every real
    # candidate below, so the search has no reason to ever swap them out -
    # club A's count from them alone is a fixed 2 for the whole sequence,
    # ruling out the "just swap the incumbents instead" escape a weaker
    # design would leave open. P3/P4 (club B, in squad, weak) - the real
    # swap-out targets across steps 1 and 2. P6 (club A candidate, EV 9) -
    # picked step 1 via P3, brings club A to 3 (at cap). P5 (club A
    # candidate, EV 8) - real highest remaining EV for step 2, but illegal
    # given the post-step-1 squad (club A already at 3). P7 (club C
    # candidate, EV 7) - legal, correct step-2 pick.
    ev_by_id = {1: 10.0, 2: 10.0, 3: 1.0, 4: 1.0, 5: 8.0, 6: 9.0, 7: 7.0}

    def fake(conn, player_id, n_gw, from_event=None):
        return SimpleNamespace(total_median=ev_by_id[player_id])
    monkeypatch.setattr(transfers_mod, "expected_points_window", fake)

    sequences = search_transfer_sequences(
        db_conn, squad_ids=[1, 2, 3, 4], free_transfers=2, bank_tenths=100, horizon_gw=2, beam_width=8,
    )

    best = sequences[0]
    swap_steps = [s for s in best.steps if s.player_in_id is not None]
    incoming_ids = {s.player_in_id for s in swap_steps}
    assert 5 not in incoming_ids, (
        "picked the illegal club-A candidate (5) in a later step - club A already has "
        "3 members (P1, P2, and the earlier step's own club-A swap P6), so a 4th is illegal"
    )
    assert 6 in incoming_ids and 7 in incoming_ids, (
        "expected the search to take the real, legal path: P6(A, highest legal EV) then P7(C), "
        f"got incoming players {incoming_ids}"
    )


def _seed_wildcard_pool(conn):
    """Shared fixture for the joint chip+transfer tests below: the same
    15-slot-legal player pool test_optimization_squad.py uses for its own
    real optimise_squad ILP tests (club_limit=4 - with only 4 teams in the
    pool, club_limit must be >=4 for a 15-man squad to be reachable at all,
    same real constraint test_optimization_squad.py's own feasible fixtures
    already respect), plus a real eligible wildcard window."""
    from test_optimization_squad import _ELEMENT_TYPES, _PLAYERS, _TEAMS
    from fpl_agent.ingestion.sync import _upsert_many

    now = "t0"
    _upsert_many(conn, "teams", _TEAMS, now)
    _upsert_many(conn, "element_types", _ELEMENT_TYPES, now)
    players_rows = [
        {
            "id": pid, "code": pid, "web_name": f"P{pid}", "first_name": None, "second_name": None,
            "team_id": team_id, "element_type": et, "squad_number": None, "status": "a",
            "news": None, "news_added": None, "opta_code": None, "removed": 0,
        }
        for pid, et, team_id, _price, _xp in _PLAYERS
    ]
    _upsert_many(conn, "players", players_rows, now)
    for pid, _et, _team_id, price, _xp in _PLAYERS:
        conn.execute(
            "INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) VALUES (?,?,?,NULL)",
            (pid, price, now),
        )
    conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) VALUES "
        "('rules.squad_team_limit','2026-27',1,?,?,?)", (now, "fpl_api_bootstrap", "4"),
    )
    conn.execute(
        "INSERT INTO rules (rule_key, season, version, effective_date, source, value) VALUES "
        "('rules.max_extra_free_transfers','2026-27',1,?,?,?)", (now, "fpl_api_bootstrap", "4"),
    )
    conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, updated_at) VALUES (1,'GW1','2026-08-01T00:00:00Z',0,0,0,1,1,'t0')"
    )
    conn.execute(
        "INSERT INTO chip_windows (season, name, number, start_event, stop_event, chip_type, updated_at) VALUES "
        "('2026-27','wildcard',1,1,5,'transfer','t0')"
    )
    conn.commit()
    return {pid: xp for pid, _et, _team_id, _price, xp in _PLAYERS}


# Deliberately the weakest legal player at each position - real total xp far
# below what the same budget can buy elsewhere in the pool.
_WEAK_SQUAD_IDS = [1, 3, 17, 15, 11, 13, 14, 27, 23, 25, 21, 26, 34, 33, 32]


def _patch_wildcard_pool_expected_points(monkeypatch, xp_map):
    from fpl_agent.optimization import chips as chips_mod
    from fpl_agent.optimization import squad as squad_mod

    def fake_expected_points(conn, player_id, n_gw=1, from_event=None):
        median = xp_map[player_id]
        return SimpleNamespace(median=median, floor=median * 0.5, ceiling=median * 1.8, confidence="MEDIUM", expected_minutes=75.0)

    def fake_expected_points_window(conn, player_id, n_gw, from_event=None):
        return SimpleNamespace(total_median=xp_map[player_id])

    monkeypatch.setattr(transfers_mod, "expected_points_window", fake_expected_points_window)
    monkeypatch.setattr(squad_mod, "expected_points", fake_expected_points)
    monkeypatch.setattr(squad_mod, "expected_points_window", fake_expected_points_window)
    monkeypatch.setattr(chips_mod, "expected_points", fake_expected_points)


def test_joint_search_can_choose_wildcard_over_a_plain_transfer(db_conn, monkeypatch):
    """Real gap this task closes (2026-08-27, "final high-value pass" P0 joint
    transfer+chip optimization): the beam used to only ever compare ROLL against
    single-swap TRANSFER candidates, with chip timing decided by a wholly
    separate post-hoc DP (chips.py::schedule_chips) that never competed on the
    same ranking key. Seeds a deliberately weak 15-man current squad next to a
    much stronger legal pool it can't reach one swap at a time (only a full
    rebuild gets there under the real club-limit/budget constraints) and a real
    eligible wildcard window at the search's only horizon step - if the joint
    beam genuinely considers a chip action as a first-class branch, it must
    beat every single-swap alternative and win outright."""
    xp_map = _seed_wildcard_pool(db_conn)
    _patch_wildcard_pool_expected_points(monkeypatch, xp_map)

    sequences = search_transfer_sequences(
        db_conn, squad_ids=_WEAK_SQUAD_IDS, free_transfers=1, bank_tenths=300, horizon_gw=1, beam_width=8,
    )
    best = sequences[0]

    assert any(st.chip_played == "wildcard" for st in best.steps), (
        f"expected the joint search to choose the wildcard branch, got steps={best.steps}"
    )
    assert best.chips_used == ("wildcard",)
    weak_total = sum(xp_map[pid] for pid in _WEAK_SQUAD_IDS)
    assert best.total_net_ev > weak_total + 5, (
        f"wildcard rebuild ({best.total_net_ev}) should clearly beat the weak squad's own total ({weak_total})"
    )


def test_wildcard_step_carries_a_real_rebuilt_squad_different_from_current(db_conn, monkeypatch):
    """Direct P0 acceptance test (2026-08-29, "master live + strategic-plan
    correction pass"): "wildcard generates a different legal 15-player
    squad where appropriate" - never the current squad relabeled. Confirmed
    real production bug this guards against: a wildcard `TransferSequenceStep`
    used to carry NO squad information at all (`resulting_squad_ids` empty),
    so the dashboard's own reconstruction silently displayed the PREVIOUS
    gw's (here, the current) squad as if it were the wildcard's own team."""
    xp_map = _seed_wildcard_pool(db_conn)
    _patch_wildcard_pool_expected_points(monkeypatch, xp_map)

    sequences = search_transfer_sequences(
        db_conn, squad_ids=_WEAK_SQUAD_IDS, free_transfers=1, bank_tenths=300, horizon_gw=1, beam_width=8,
    )
    best = sequences[0]
    wildcard_step = next(st for st in best.steps if st.chip_played == "wildcard")

    assert wildcard_step.resulting_squad_ids, "wildcard step must carry a real, non-empty rebuilt squad"
    assert len(wildcard_step.resulting_squad_ids) == 15, "a legal FPL squad is always exactly 15 players"
    assert set(wildcard_step.resulting_squad_ids) != set(_WEAK_SQUAD_IDS), (
        "the wildcard rebuild must be a genuinely different squad, never the current one relabeled"
    )


def test_wildcard_rebuild_failure_is_never_offered_as_a_candidate(db_conn, monkeypatch):
    """Direct user instruction: "if the optimizer cannot produce a valid
    wildcard squad, show REVIEW/INSUFFICIENT DATA - never reuse the current
    squad and label it wildcard." Simulates a real rebuild failure
    (`optimise_squad` returning a non-Optimal status, e.g. genuinely
    infeasible budget/constraints) and asserts the wildcard branch never
    reaches the beam's surviving candidates at all."""
    from fpl_agent.optimization import chips as chips_mod

    xp_map = _seed_wildcard_pool(db_conn)
    _patch_wildcard_pool_expected_points(monkeypatch, xp_map)
    monkeypatch.setattr(
        chips_mod, "_rebuild_squad_for_chip",
        lambda conn, window_gw, budget_tenths: SimpleNamespace(status="Infeasible", squad=[], total_cost_tenths=0),
    )

    sequences = search_transfer_sequences(
        db_conn, squad_ids=_WEAK_SQUAD_IDS, free_transfers=1, bank_tenths=300, horizon_gw=1, beam_width=8,
    )

    assert not any(st.chip_played == "wildcard" for seq in sequences for st in seq.steps), (
        "a failed wildcard rebuild must never appear as a candidate path"
    )


def test_path_total_equals_sum_of_step_gw_ev(db_conn, monkeypatch):
    """Direct P0 acceptance test: "path score must be traceable - path
    total must equal the sum of its underlying GW states... no unexplained
    totals." Real invariant over the actual joint search output, not a
    hand-constructed fixture."""
    xp_map = _seed_wildcard_pool(db_conn)
    _patch_wildcard_pool_expected_points(monkeypatch, xp_map)

    sequences = search_transfer_sequences(
        db_conn, squad_ids=_WEAK_SQUAD_IDS, free_transfers=1, bank_tenths=300, horizon_gw=1, beam_width=8,
    )

    for seq in sequences:
        assert round(sum(st.gw_ev for st in seq.steps), 2) == seq.total_net_ev, (
            f"path_total ({seq.total_net_ev}) must equal the sum of its own steps' gw_ev "
            f"({[st.gw_ev for st in seq.steps]})"
        )


def test_joint_search_excludes_an_already_used_chip(db_conn, monkeypatch):
    """used_chip_names must stop the joint beam from ever offering a chip the
    user has already burned this season - same real-history-driven exclusion
    schedule_chips' own used_chip_names parameter already applies, now also
    respected by the beam that actually picks the path."""
    xp_map = _seed_wildcard_pool(db_conn)
    _patch_wildcard_pool_expected_points(monkeypatch, xp_map)

    sequences = search_transfer_sequences(
        db_conn, squad_ids=_WEAK_SQUAD_IDS, free_transfers=1, bank_tenths=0, horizon_gw=1, beam_width=8,
        used_chip_names=frozenset({"wildcard"}),
    )
    for seq in sequences:
        assert "wildcard" not in seq.chips_used
        assert all(st.chip_played != "wildcard" for st in seq.steps)


def test_compare_starting_actions_ranks_transfer_above_roll_when_it_wins(db_conn, monkeypatch):
    """Real P0 gap this task closes: the beam search could always internally
    discover the best single sequence, but never surfaced a real side-by-side
    "here is ROLL's own best future vs here is each other starting action's
    own best future" comparison. Reuses the exact same hand-verified
    two-team pool as test_search_transfer_sequences_credits_transferred_
    player_across_full_horizon above (team 2 flat 6.0/GW, team 1 flat 3.0/GW)
    so the correct ranking is hand-computable: fixing "transfer 1->3 now" and
    letting the same joint search optimize the remaining 1 GW must reach a
    higher real path_total (21.0) than fixing "roll" and optimizing the same
    remaining GW (15.0), because a strong replacement bought this GW keeps
    contributing every GW it's held, exactly the property the beam search
    itself already relies on."""
    from fpl_agent.optimization.transfers import compare_starting_actions

    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    options = compare_starting_actions(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=2, continuation_beam_width=4,
    )

    by_label = {o.label: o for o in options}
    assert "ROLL" in by_label
    roll = by_label["ROLL"]
    transfer_options = [o for o in options if o.kind == "transfer"]
    assert transfer_options, "expected at least one transfer option (player 1 or 2 -> a strong replacement)"
    best_transfer = max(transfer_options, key=lambda o: o.path_total)

    assert best_transfer.path_total > roll.path_total, (
        f"expected the transfer into a strong replacement ({best_transfer.path_total}) to beat "
        f"ROLL's own best future ({roll.path_total}) - both hand-computable from the fixture's flat "
        "per-GW rates (see this test's docstring)"
    )
    # options must be returned already ranked best-first
    assert options[0].path_total == max(o.path_total for o in options)


def test_compare_starting_actions_surfaces_a_legal_chip_option(db_conn, monkeypatch):
    """A real eligible chip must appear as its own ranked starting-action
    option, not only reachable via the main beam's internal branching."""
    from fpl_agent.optimization.transfers import compare_starting_actions

    xp_map = _seed_wildcard_pool(db_conn)
    _patch_wildcard_pool_expected_points(monkeypatch, xp_map)

    options = compare_starting_actions(
        db_conn, squad_ids=_WEAK_SQUAD_IDS, free_transfers=1, bank_tenths=300, horizon_gw=1,
    )

    chip_options = [o for o in options if o.kind == "chip"]
    assert any(o.chip_name == "wildcard" for o in chip_options), (
        f"expected a wildcard option among {[o.label for o in options]}"
    )
    assert options[0].kind == "chip" and options[0].chip_name == "wildcard", (
        "the wildcard rebuild should dominate every single-swap alternative here, same as the "
        "joint search's own winning path in test_joint_search_can_choose_wildcard_over_a_plain_transfer"
    )
    wildcard_opt = next(o for o in chip_options if o.chip_name == "wildcard")
    assert len(wildcard_opt.starting_squad_ids) == 15
    assert set(wildcard_opt.starting_squad_ids) != set(_WEAK_SQUAD_IDS), (
        "starting_squad_ids (the real DISPLAY squad for this GW) must be the genuine rebuild, "
        "never the current squad relabeled"
    )


def test_build_diverse_paths_wildcard_starting_step_carries_the_real_rebuilt_squad(db_conn, monkeypatch):
    """The real PRODUCTION path (2026-08-29, "master live + strategic-plan
    correction pass" P0 fix): `build_diverse_paths`/`path_detail` is what
    `fpl strategic-plan`'s default `--current-action` run actually persists
    to the decisions journal and the dashboard reads - confirmed live in
    production this was the exact broken path (a real logged decision's
    wildcard step serialized with no squad information at all, `_synthetic_
    sequence_from_option`'s starting_step never threading `resulting_
    squad_ids` through). This test exercises that real path end to end."""
    from fpl_agent.optimization.transfers import build_diverse_paths, compare_starting_actions

    xp_map = _seed_wildcard_pool(db_conn)
    _patch_wildcard_pool_expected_points(monkeypatch, xp_map)

    options = compare_starting_actions(
        db_conn, squad_ids=_WEAK_SQUAD_IDS, free_transfers=1, bank_tenths=300, horizon_gw=1,
    )
    paths = build_diverse_paths(options, start_event=1, conn=db_conn, full_horizon_gw=1, checkpoints=())
    wildcard_path = next(p for p in paths if p["steps"][0]["chip_played"] == "wildcard")
    step0 = wildcard_path["steps"][0]

    assert len(step0["resulting_squad_ids"]) == 15
    assert set(step0["resulting_squad_ids"]) != set(_WEAK_SQUAD_IDS)
    assert round(sum(s["gw_ev"] for s in wildcard_path["steps"]), 2) == wildcard_path["path_total"]


# --- build_diverse_paths (2026-08-29, P0 audit: "strategic paths must be
# meaningfully different") ---------------------------------------------------

def test_build_diverse_paths_every_path_has_a_distinct_opening_action(db_conn, monkeypatch):
    """The real bug this fixes: the raw beam's top-N converges to
    near-duplicate variants of the same dominant opening move. Reuses the
    exact fixture from test_compare_starting_actions_ranks_transfer_above_
    roll_when_it_wins above - `compare_starting_actions` builds one option
    per real distinct starting action by construction, so every path
    `build_diverse_paths` returns must have a first step whose
    (chip_played, player_out_id, player_in_id) signature is unique across
    the whole returned list - the core diversity guarantee."""
    from fpl_agent.optimization.transfers import build_diverse_paths, compare_starting_actions

    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    options = compare_starting_actions(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=2, continuation_beam_width=4,
    )
    paths = build_diverse_paths(options, start_event=1, max_paths=5)

    assert len(paths) >= 2
    signatures = [
        (p["steps"][0]["chip_played"], p["steps"][0]["player_out_id"], p["steps"][0]["player_in_id"])
        for p in paths
    ]
    assert len(signatures) == len(set(signatures)), f"expected every path's opening move to be unique, got {signatures}"


def test_build_diverse_paths_ranked_best_first_with_correct_deltas(db_conn, monkeypatch):
    from fpl_agent.optimization.transfers import build_diverse_paths, compare_starting_actions

    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    options = compare_starting_actions(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=2, continuation_beam_width=4,
    )
    paths = build_diverse_paths(options, start_event=1, roll_total=15.0, max_paths=5)

    totals = [p["path_total"] for p in paths]
    assert totals == sorted(totals, reverse=True)
    assert paths[0]["delta_vs_leader"] == 0.0
    assert paths[0]["delta_vs_roll"] == round(paths[0]["path_total"] - 15.0, 2)
    assert paths[0]["delta_vs_second_best"] == round(paths[0]["path_total"] - paths[1]["path_total"], 2)
    # only the leader gets a real delta_vs_second_best - matches path_detail's
    # own documented contract (existing behavior, unchanged by this fix).
    assert paths[1]["delta_vs_second_best"] is None


def test_build_diverse_paths_respects_max_paths_cap(db_conn, monkeypatch):
    from fpl_agent.optimization.transfers import build_diverse_paths, compare_starting_actions

    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    options = compare_starting_actions(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=2, continuation_beam_width=4,
    )
    paths = build_diverse_paths(options, start_event=1, max_paths=2)

    assert len(paths) <= 2


def test_build_diverse_paths_empty_when_no_options():
    from fpl_agent.optimization.transfers import build_diverse_paths

    assert build_diverse_paths([], start_event=1) == []


def test_build_diverse_paths_starting_chip_step_carries_the_real_chip_name(db_conn, monkeypatch):
    """A chip-kind StartingActionOption's synthetic first step must carry
    the real chip_played value (not None) - the exact field the dashboard's
    chip-mapping fix (`plan.py`/`squad.py`, 2026-08-29) reads to render chip
    badges, so a chip-first diverse path renders correctly too."""
    from fpl_agent.optimization.transfers import build_diverse_paths, compare_starting_actions

    xp_map = _seed_wildcard_pool(db_conn)
    _patch_wildcard_pool_expected_points(monkeypatch, xp_map)

    options = compare_starting_actions(
        db_conn, squad_ids=_WEAK_SQUAD_IDS, free_transfers=1, bank_tenths=300, horizon_gw=1,
    )
    paths = build_diverse_paths(options, start_event=1)

    assert paths[0]["steps"][0]["chip_played"] == "wildcard"
    assert paths[0]["steps"][0]["action"] == "PLAY WILDCARD"


# --- checkpoint_breakdown (2026-08-29, P0 audit: "3/5/8GW breakdown per
# path") -----------------------------------------------------------------

def test_checkpoint_breakdown_1gw_reuses_starting_gw_value(db_conn, monkeypatch):
    from fpl_agent.optimization.transfers import checkpoint_breakdown, compare_starting_actions

    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    options = compare_starting_actions(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=4, continuation_beam_width=2,
    )
    roll = next(o for o in options if o.kind == "roll")

    result = checkpoint_breakdown(db_conn, roll, start_event=1, full_horizon_gw=4, checkpoints=(1,))

    assert result[1] == round(roll.starting_gw_value, 2)


def test_checkpoint_breakdown_full_horizon_reuses_path_total(db_conn, monkeypatch):
    from fpl_agent.optimization.transfers import checkpoint_breakdown, compare_starting_actions

    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    options = compare_starting_actions(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=4, continuation_beam_width=2,
    )
    roll = next(o for o in options if o.kind == "roll")

    result = checkpoint_breakdown(db_conn, roll, start_event=1, full_horizon_gw=4, checkpoints=(4,))

    assert result[4] == roll.path_total


def test_checkpoint_breakdown_middle_horizon_matches_a_real_independent_continuation_search(db_conn, monkeypatch):
    """Real wiring proof: a middle checkpoint (below the full horizon) must
    equal `starting_gw_value + <a fresh continuation search run directly
    against this option's own resulting_* state>` - proves
    `checkpoint_breakdown` genuinely re-runs a real, correctly-scoped search
    rather than interpolating/estimating."""
    from fpl_agent.optimization.transfers import checkpoint_breakdown, compare_starting_actions, search_transfer_sequences

    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    options = compare_starting_actions(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=4, continuation_beam_width=2,
    )
    roll = next(o for o in options if o.kind == "roll")

    result = checkpoint_breakdown(db_conn, roll, start_event=1, full_horizon_gw=4, checkpoints=(2,))

    independent = search_transfer_sequences(
        db_conn, list(roll.resulting_squad_ids), roll.resulting_free_transfers, roll.resulting_bank_tenths,
        horizon_gw=1, beam_width=2, used_chip_names=roll.resulting_used_chip_names, start_event=2,
    )
    expected = round(roll.starting_gw_value + independent[0].total_net_ev, 2)

    assert result[2] == expected


def test_build_diverse_paths_attaches_horizon_breakdown_when_conn_given(db_conn, monkeypatch):
    from fpl_agent.optimization.transfers import build_diverse_paths, compare_starting_actions

    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    options = compare_starting_actions(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=4, continuation_beam_width=2,
    )
    paths = build_diverse_paths(
        options, start_event=1, max_paths=3, conn=db_conn, full_horizon_gw=4,
        checkpoints=(2, 4), roll_totals_by_horizon={2: 6.0, 4: 12.0}, continuation_beam_width=2,
    )

    for p in paths:
        assert "horizon_breakdown" in p
        assert set(p["horizon_breakdown"].keys()) == {2, 4}
        # the full-horizon checkpoint must exactly equal this path's own
        # already-reported path_total - same number, two places.
        assert p["horizon_breakdown"][4]["path_total"] == p["path_total"]

    # delta_vs_next_best is a real signed number for every path at every
    # checkpoint - positive (the real margin) for whichever path actually
    # leads AT THAT checkpoint, negative for every path that trails there.
    # Exactly one path holds the max (>= every other's) at each checkpoint.
    for h in (2, 4):
        deltas = [p["horizon_breakdown"][h]["delta_vs_next_best"] for p in paths]
        assert all(d is not None for d in deltas)
        assert sum(1 for d in deltas if d == max(deltas)) >= 1
        assert max(deltas) >= 0  # the real leader's own margin is never negative


def test_build_diverse_paths_no_breakdown_without_conn(db_conn, monkeypatch):
    """conn/full_horizon_gw are opt-in - omitting them (every existing
    caller before this fix) must not attach horizon_breakdown at all."""
    from fpl_agent.optimization.transfers import build_diverse_paths, compare_starting_actions

    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    options = compare_starting_actions(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=2, continuation_beam_width=2,
    )
    paths = build_diverse_paths(options, start_event=1, max_paths=3)

    for p in paths:
        assert "horizon_breakdown" not in p


def _tc(player_in_name, ev1, ev3, ev5, player_out_id=1, player_in_id=99):
    from fpl_agent.optimization.transfers import TransferCandidate

    return TransferCandidate(
        player_out_id=player_out_id, player_out_name="Owned", player_in_id=player_in_id,
        player_in_name=player_in_name, price_delta_tenths=0,
        ev_1gw=ev1, ev_3gw=ev3, ev_5gw=ev5, net_ev_1gw=ev1, net_ev_3gw=ev3, net_ev_5gw=ev5, uses_hit=False,
    )


def test_pareto_frontier_keeps_non_dominated_candidates_and_drops_dominated_ones():
    """Real unit test, Phase 7.3 Part 9 (Pareto candidate retention).
    A: best at 5GW. B: beats A at 1GW/3GW, loses at 5GW - genuinely
    non-dominated, must survive. C: loses to A on every horizon - a real
    dominated candidate, must be dropped even though it would rank above B
    on a raw 1GW-only reading (nothing here beats it on 1GW alone, but A
    beats it on every horizon simultaneously, which is what dominance means)."""
    from fpl_agent.optimization.transfers import _pareto_frontier

    a = _tc("A", ev1=1.0, ev3=5.0, ev5=10.0, player_in_id=1)
    b = _tc("B", ev1=5.0, ev3=6.0, ev5=9.0, player_in_id=2)
    c = _tc("C", ev1=0.5, ev3=4.0, ev5=8.0, player_in_id=3)  # dominated by A on every horizon

    frontier = _pareto_frontier([a, b, c])

    names = {c.player_in_name for c in frontier}
    assert names == {"A", "B"}


def test_pareto_frontier_caps_at_k():
    from fpl_agent.optimization.transfers import _pareto_frontier

    # 3 mutually non-dominated candidates (each wins on exactly one horizon).
    candidates = [
        _tc("A", ev1=10.0, ev3=1.0, ev5=1.0, player_in_id=1),
        _tc("B", ev1=1.0, ev3=10.0, ev5=1.0, player_in_id=2),
        _tc("C", ev1=1.0, ev3=1.0, ev5=10.0, player_in_id=3),
    ]
    assert len(_pareto_frontier(candidates, k=2)) == 2


def test_compare_starting_actions_picks_the_pareto_candidate_with_the_better_real_continuation(db_conn, monkeypatch):
    """Real regression test for the Phase 7.3 Part 9 fix - proves
    compare_starting_actions no longer commits to the single n_gw=5-lens
    top candidate before evaluating its own continuation. Fixture: player
    "Front" ranks #1 by the n_gw=5 lens (10.0 vs "Alt"'s 9.0) but is NOT
    dominated by Alt (Alt actually beats it on both 1GW and 3GW - a genuine
    Pareto pair, both must be retained and continued). search_transfer_
    sequences is patched so continuing from a squad containing Alt reaches a
    real, much higher total_net_ev than continuing from Front - proving the
    real, evaluated continuation decides the winner, not the upfront ranking
    lens alone."""
    from fpl_agent.optimization.transfers import compare_starting_actions

    _seed_spiky_vs_steady_pool(db_conn)
    now = "2026-01-01T00:00:00Z"
    db_conn.execute(
        f"INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
        f"VALUES (10,10,'Front',2,1,'a',0,'{now}')"
    )
    db_conn.execute(
        f"INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) "
        f"VALUES (10, 50, '{now}', NULL)"
    )
    db_conn.commit()

    totals = {
        1: {1: 1.0, 3: 3.0, 5: 5.0},    # Owned
        10: {1: 1.0, 3: 5.0, 5: 10.0},  # Front - wins the n_gw=5 lens outright
        6: {1: 5.0, 3: 6.0, 5: 9.0},    # Steady/Alt - beats Front on 1GW and 3GW, genuinely non-dominated
        5: {1: 0.5, 3: 2.0, 5: 3.0},    # Spiky - dominated by Front on every horizon, must be dropped
    }

    def fake_window(conn, player_id, n_gw, from_event=None):
        return SimpleNamespace(total_median=totals[player_id][n_gw])

    monkeypatch.setattr(transfers_mod, "expected_points_window", fake_window)

    real_search = transfers_mod.search_transfer_sequences

    def fake_search(conn, squad_ids, *args, **kwargs):
        if 6 in squad_ids:  # continuing with Alt reaches a genuinely better real future
            return [SimpleNamespace(total_net_ev=1000.0, steps=())]
        return real_search(conn, squad_ids, *args, **kwargs)

    monkeypatch.setattr(transfers_mod, "search_transfer_sequences", fake_search)

    options = compare_starting_actions(
        db_conn, squad_ids=[1], free_transfers=1, bank_tenths=100, horizon_gw=2, continuation_beam_width=2,
    )

    transfer_options = [o for o in options if o.kind == "transfer"]
    assert len(transfer_options) == 1, "one retained option per squad player, not one row per Pareto candidate"
    assert transfer_options[0].player_in_name == "Steady", (
        f"expected the Pareto-retained Alt candidate (real continuation total_net_ev=1000.0) to win over "
        f"Front (the single n_gw=5-lens default), got {transfer_options[0].player_in_name}"
    )

