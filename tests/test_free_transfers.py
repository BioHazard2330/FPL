"""Real free-transfer (FT) state derivation (2026-08-27, "final product
pass", Part 3) - `models.free_transfers.compute_real_free_transfers` replays
official FPL history (`my_team_gw_summary.event_transfers` +
`my_team_picks.active_chip`) rather than guessing. Every scenario here
checks the exact real FPL accumulation rule by hand.

2026-09-02: fixed a real, confirmed production bug (dashboard showed 3 free
transfers for GW3, the real FPL app showed 2). Event 1 (the initial squad
pick, before GW1's own deadline) has no real free-transfer mechanic - the
old algorithm gave it a phantom `available=1` anyway via the same formula
every real transfer window uses, then rolled whatever was left of that
phantom FT into GW2 - inflating every subsequent gameweek's real bank by 1,
permanently. The real accumulation only begins with the GW2 window, which
always starts flat at 1 (never a rollover from a GW1 that never had a real
FT to roll). Every expected value below reflects the corrected rule."""
from fpl_agent.models.free_transfers import (
    compute_current_free_transfers,
    compute_real_free_transfers,
    count_pending_transfers,
)


def _seed_gw_summary(conn, entry_id, event, event_transfers):
    conn.execute(
        "INSERT INTO my_team_gw_summary (entry_id, event, points, total_points, overall_rank, "
        "bank_tenths, team_value_tenths, event_transfers, event_transfers_cost, points_on_bench, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (entry_id, event, 50, 50, 1000, 0, 1000, event_transfers, 0, 0, "t0"),
    )


def _seed_chip(conn, entry_id, event, chip_name):
    conn.execute(
        "INSERT INTO my_team_picks (entry_id, event, player_id, squad_slot, multiplier, "
        "is_captain, is_vice_captain, active_chip, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (entry_id, event, 1, 1, 1, 0, 0, chip_name, "t0"),
    )


def test_returns_none_with_no_real_history(db_conn):
    assert compute_real_free_transfers(db_conn, 7378572) is None


def test_gw1_has_no_ft_mechanic_gw2_starts_flat_at_one(db_conn):
    """Real, well-known FPL rule: GW1 (the initial squad pick) has no real
    free-transfer mechanic at all - the FT accumulation only begins with the
    GW2 transfer window, which always starts flat at 1 (never "1 rolled + 1
    new" - there is nothing real to roll from a gameweek that never had a
    free transfer in the first place)."""
    _seed_gw_summary(db_conn, 7378572, 1, event_transfers=0)
    db_conn.commit()

    assert compute_real_free_transfers(db_conn, 7378572) == 1


def test_using_the_free_transfer_resets_to_one(db_conn):
    _seed_gw_summary(db_conn, 7378572, 1, event_transfers=0)
    _seed_gw_summary(db_conn, 7378572, 2, event_transfers=1)
    db_conn.commit()

    # walking into GW2: available=1 (flat baseline, GW1 has no FT to roll),
    # used 1 -> carry 0 -> walking into GW3: min(0+1,5)=1
    assert compute_real_free_transfers(db_conn, 7378572) == 1


def test_taking_a_hit_floors_at_zero_not_negative(db_conn):
    _seed_gw_summary(db_conn, 7378572, 1, event_transfers=0)
    _seed_gw_summary(db_conn, 7378572, 2, event_transfers=5)
    db_conn.commit()

    # available=1 (flat baseline), used 5 (a real hit) -> carry max(1-5,0)=0 -> next FT = min(0+1,cap)=1
    assert compute_real_free_transfers(db_conn, 7378572) == 1


def test_caps_at_configured_max(db_conn):
    for event in range(1, 8):
        _seed_gw_summary(db_conn, 7378572, event, event_transfers=0)
    db_conn.commit()

    # rules.max_extra_free_transfers defaults to 4 -> cap = 5; still reached
    # with 6 real accumulating windows (GW2-GW7) even from the corrected
    # flat-1 GW2 baseline.
    assert compute_real_free_transfers(db_conn, 7378572) == 5


def test_wildcard_transfers_never_touch_the_bank(db_conn):
    """Real FPL rule: wildcard/free-hit transfers are unlimited and free -
    they must not reduce the FT bank the way a normal transfer would."""
    _seed_gw_summary(db_conn, 7378572, 1, event_transfers=0)
    _seed_gw_summary(db_conn, 7378572, 2, event_transfers=12)
    _seed_chip(db_conn, 7378572, 2, "wildcard")
    db_conn.commit()

    # available=1 walking into GW2 (flat baseline; real wildcard use),
    # untouched by the 12 "transfers" it made -> carry=1 -> next FT = min(1+1,5)=2
    assert compute_real_free_transfers(db_conn, 7378572) == 2


def test_a_gap_in_synced_history_returns_none_not_a_guess(db_conn):
    _seed_gw_summary(db_conn, 7378572, 1, event_transfers=0)
    _seed_gw_summary(db_conn, 7378572, 3, event_transfers=0)  # event 2 missing
    db_conn.commit()

    assert compute_real_free_transfers(db_conn, 7378572) is None


def test_upto_event_lets_a_caller_ask_about_an_earlier_point(db_conn):
    _seed_gw_summary(db_conn, 7378572, 1, event_transfers=0)
    _seed_gw_summary(db_conn, 7378572, 2, event_transfers=0)
    _seed_gw_summary(db_conn, 7378572, 3, event_transfers=0)
    db_conn.commit()

    assert compute_real_free_transfers(db_conn, 7378572, upto_event=1) == 1
    assert compute_real_free_transfers(db_conn, 7378572, upto_event=2) == 2


def _seed_transfer(conn, entry_id, event, element_in, element_out, time):
    conn.execute(
        "INSERT INTO my_team_transfers (entry_id, event, element_in, element_in_cost, "
        "element_out, element_out_cost, transfer_time, retrieved_at) VALUES (?,?,?,?,?,?,?,?)",
        (entry_id, event, element_in, 50, element_out, 50, time, "t0"),
    )


def test_count_pending_transfers_is_zero_with_no_synced_transfers(db_conn):
    assert count_pending_transfers(db_conn, 7378572, 3) == 0


def test_count_pending_transfers_counts_real_logged_rows_for_that_event(db_conn):
    _seed_transfer(db_conn, 7378572, 3, 100, 200, "2026-09-03T10:00:00Z")
    _seed_transfer(db_conn, 7378572, 3, 300, 400, "2026-09-03T11:00:00Z")
    _seed_transfer(db_conn, 7378572, 4, 500, 600, "2026-09-10T10:00:00Z")  # a different, later window
    db_conn.commit()

    assert count_pending_transfers(db_conn, 7378572, 3) == 2
    assert count_pending_transfers(db_conn, 7378572, 4) == 1


def test_compute_current_free_transfers_nets_out_a_pending_window_transfer(db_conn):
    """Real production scenario this fix closes: GW1/GW2 both show 0
    transfers in the official (locked) history, so the corrected replay
    banks 2 for GW3 - but the user already spent 1 of those in GW3's
    still-open pre-deadline window via the real `/entry/{id}/transfers/`
    log, which `compute_real_free_transfers` alone can't see."""
    _seed_gw_summary(db_conn, 7378572, 1, event_transfers=0)
    _seed_gw_summary(db_conn, 7378572, 2, event_transfers=0)
    _seed_transfer(db_conn, 7378572, 3, 100, 200, "2026-09-03T10:00:00Z")
    db_conn.commit()

    assert compute_real_free_transfers(db_conn, 7378572) == 2
    assert compute_current_free_transfers(db_conn, 7378572) == 1


def test_compute_current_free_transfers_never_goes_negative(db_conn):
    _seed_gw_summary(db_conn, 7378572, 1, event_transfers=0)
    for i in range(5):
        _seed_transfer(db_conn, 7378572, 2, 100 + i, 200 + i, f"2026-08-25T1{i}:00:00Z")
    db_conn.commit()

    assert compute_current_free_transfers(db_conn, 7378572) == 0
