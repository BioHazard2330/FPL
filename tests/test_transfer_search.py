# tests/test_transfer_search.py
import sqlite3
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
        f"INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        f"VALUES (1,'Forward','FWD','Forwards','{now}')"
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
        "('rules.max_extra_free_transfers','2026-27',1,'2026-08-01','fpl_api','4')"
    )
    conn.commit()


def _patch_expected_points_window(monkeypatch):
    def fake(conn, player_id, n_gw, from_event=None):
        return SimpleNamespace(total_median=_PLAYER_GW_EV[player_id])

    monkeypatch.setattr(transfers_mod, "expected_points_window", fake)


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

    # free_transfers=0 forces every transfer this step to be a hit. start_event=1
    # (the only seeded event, is_next=1) is exactly 1 GW before the wildcard's
    # start_event=2 - within WILDCARD_PROXIMITY_GWS=1.
    sequences = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=0, bank_tenths=100, horizon_gw=1, beam_width=4,
    )
    best = sequences[0]
    # Hand-computed with the penalty correctly applied: roll = 3.0+3.0 = 6.0,
    # score 6.0. A hit-swap into a strong player = 3.0(unswapped weak
    # player)+8.0(strong player) = 11.0, minus HIT_COST(4.0) minus
    # WILDCARD_PROXIMITY_PENALTY(2.0) = score 5.0. Roll wins, 6.0 vs 5.0. If the
    # penalty were silently not applied (chip_type-vs-name bug), the hit-swap
    # would instead score 11.0-4.0=7.0 and WIN over roll's 6.0 - so this
    # assertion (and the exact score check) genuinely depends on the penalty
    # firing, not just on roll being generically favoured.
    assert not best.steps[0].uses_hit, (
        "roll should beat a hit-transfer one GW before an eligible wildcard window "
        "in this scenario (6.0 vs 5.0 with the penalty applied; without it the hit "
        "would score 7.0 and incorrectly win) - if this fails, check whether the "
        "wildcard-proximity check is matching on ChipWindow.chip_type instead of .name"
    )
    assert best.total_net_ev == 6.0


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
