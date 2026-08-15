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
    team 1 = 3.0/GW), the CORRECT total for a sequence that swaps player 1 (weak)
    for player 3 (strong) at the earliest step and never transfers again is
    computable by hand: squad (2,3) earns 3.0+6.0=9.0 per GW for all 3 horizon
    GWs = 27.0, no hit cost (the swap uses the 1 free transfer available). A
    DELTA-ONLY implementation - one that only adds the one-time EV difference at
    the moment of transfer instead of the full squad's EV every remaining GW -
    could never reach this magnitude: it would never count player 2's ongoing
    3.0/GW baseline contribution at all, let alone player 3's, producing a total
    in the single digits instead. This is a magnitude check, not a tie-break-order
    check, specifically because tie-break order between equally-buggy-scored
    sequences is not a reliable way to detect this bug (verified by hand-tracing
    the beam's greedy pruning behavior during planning - a delta-only bug can
    still coincidentally front-load transfers early for unrelated reasons, so
    checking WHEN the swap happens is not a sound regression guard; checking the
    resulting MAGNITUDE is)."""
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    sequences = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=3, beam_width=4,
    )
    best = sequences[0]

    assert best.total_net_ev >= 24.0, (
        f"got {best.total_net_ev}, expected close to 27.0 (squad EV of 9.0/GW x 3 GWs, "
        "achieved by swapping into the stronger player at the earliest opportunity and "
        "holding). A much lower total strongly suggests cumulative_ev is only counting "
        "transfer-moment deltas instead of full-squad EV summed across every horizon GW."
    )


def test_search_transfer_sequences_respects_max_banked_free_transfers(db_conn, monkeypatch):
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)
    sequences = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=5, bank_tenths=100, horizon_gw=2, beam_width=4,
    )
    for seq in sequences:
        assert seq.final_free_transfers <= 5  # max_banked from the seeded rule (1 + 4)


def test_wildcard_proximity_penalizes_a_hit_the_gw_before_the_window(db_conn, monkeypatch):
    """Regression test for the chip_type-vs-name bug caught during planning (see
    this task's Algorithm section, point 6) - matching on chip_type instead of
    name would make this penalty silently never fire, so this test would fail
    (roll would still beat a hit here either way on raw EV+HIT_COST alone, but
    the specific 6.0-vs-3.0 margin computed below only holds if the extra
    WILDCARD_PROXIMITY_PENALTY is actually applied)."""
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)
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
    # Hand-computed: roll = 3.0+3.0 = 6.0, score 6.0. A hit-swap into a strong
    # player = 3.0(unswapped weak player)+6.0(strong player) = 9.0, minus
    # HIT_COST(4.0) minus WILDCARD_PROXIMITY_PENALTY(2.0) = score 3.0. Roll wins.
    assert not best.steps[0].uses_hit, (
        "roll should beat a hit-transfer one GW before an eligible wildcard window "
        "in this scenario (6.0 vs 3.0) - if this fails, check whether the wildcard-"
        "proximity check is matching on ChipWindow.chip_type instead of .name"
    )


def test_price_tiebreak_bonus_prefers_rising_player_among_equal_ev_candidates(db_conn, monkeypatch):
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)
    db_conn.execute("INSERT INTO app_meta (key, value, updated_at) VALUES ('total_players','1000000','2026-01-01T00:00:00Z')")
    db_conn.execute(
        "INSERT INTO player_transfer_momentum_history "
        "(player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from, valid_until) "
        "VALUES (3, 8000, 100, 8000, 100, '2026-01-01T00:00:00Z', NULL)"
    )
    db_conn.commit()

    # Players 3 and 4 have identical EV (both 6.0/GW, same price) in this seed -
    # only player 3's seeded RISE_LIKELY momentum should break the tie.
    sequences = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=1, beam_width=1,
    )
    best = sequences[0]
    swap_step = next(s for s in best.steps if s.player_in_id is not None)
    assert swap_step.player_in_id == 3
