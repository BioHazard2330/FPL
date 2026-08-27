"""Real free-transfer (FT) state derivation (2026-08-27, "final product
pass", Part 3) - `models.free_transfers.compute_real_free_transfers` replays
official FPL history (`my_team_gw_summary.event_transfers` +
`my_team_picks.active_chip`) rather than guessing. Every scenario here
checks the exact real FPL accumulation rule by hand."""
from fpl_agent.models.free_transfers import compute_real_free_transfers


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


def test_gw1_zero_transfers_gives_two_ft_for_gw2(db_conn):
    """Real, well-known FPL rule: making no transfers in your first
    gameweek leaves you with 2 free transfers for GW2 (1 rolled + 1 new)."""
    _seed_gw_summary(db_conn, 7378572, 1, event_transfers=0)
    db_conn.commit()

    assert compute_real_free_transfers(db_conn, 7378572) == 2


def test_using_the_free_transfer_resets_to_one(db_conn):
    _seed_gw_summary(db_conn, 7378572, 1, event_transfers=0)
    _seed_gw_summary(db_conn, 7378572, 2, event_transfers=1)
    db_conn.commit()

    # walking into GW2: available=2, used 1 -> carry 1 -> walking into GW3: 1+1=2
    assert compute_real_free_transfers(db_conn, 7378572) == 2


def test_taking_a_hit_floors_at_zero_not_negative(db_conn):
    _seed_gw_summary(db_conn, 7378572, 1, event_transfers=0)
    _seed_gw_summary(db_conn, 7378572, 2, event_transfers=5)
    db_conn.commit()

    # available=2, used 5 (a real hit) -> carry max(2-5,0)=0 -> next FT = min(0+1,cap)=1
    assert compute_real_free_transfers(db_conn, 7378572) == 1


def test_caps_at_configured_max(db_conn):
    for event in range(1, 8):
        _seed_gw_summary(db_conn, 7378572, event, event_transfers=0)
    db_conn.commit()

    # rules.max_extra_free_transfers defaults to 4 -> cap = 5
    assert compute_real_free_transfers(db_conn, 7378572) == 5


def test_wildcard_transfers_never_touch_the_bank(db_conn):
    """Real FPL rule: wildcard/free-hit transfers are unlimited and free -
    they must not reduce the FT bank the way a normal transfer would."""
    _seed_gw_summary(db_conn, 7378572, 1, event_transfers=0)
    _seed_gw_summary(db_conn, 7378572, 2, event_transfers=12)
    _seed_chip(db_conn, 7378572, 2, "wildcard")
    db_conn.commit()

    # available=2 walking into GW2 (real wildcard use), untouched by the 12
    # "transfers" it made -> carry=2 -> next FT = min(2+1,5)=3
    assert compute_real_free_transfers(db_conn, 7378572) == 3


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

    assert compute_real_free_transfers(db_conn, 7378572, upto_event=1) == 2
    assert compute_real_free_transfers(db_conn, 7378572, upto_event=2) == 3
