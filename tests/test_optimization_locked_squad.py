from fpl_agent.database.decisions import log_decision
from fpl_agent.ingestion.my_team import set_my_team_entry_id
from fpl_agent.optimization.locked_squad import get_locked_squad, is_locked
from test_optimization_squad import _PLAYERS, _patch_expected_points, _seed

_STARTING_11 = [1, 10, 11, 12, 13, 20, 21, 22, 30, 31, 32]
_BENCH_4 = [2, 14, 23, 33]
_FULL_15 = _STARTING_11 + _BENCH_4


def _seed_real_picks(conn, event=1, entry_id=7378572, captain_id=30, vice_id=20):
    set_my_team_entry_id(conn, entry_id)
    conn.execute(
        "INSERT INTO my_team_entry (entry_id, manager_name, region_name, favourite_team_id, "
        "joined_time, started_event, retrieved_at) VALUES (?,?,?,?,?,?,?)",
        (entry_id, "Test Manager", "Testland", 1, "t0", 1, "t0"),
    )
    conn.execute(
        "INSERT INTO my_team_gw_summary (entry_id, event, points, total_points, overall_rank, "
        "bank_tenths, team_value_tenths, event_transfers, event_transfers_cost, points_on_bench, retrieved_at) "
        "VALUES (?,?,0,0,NULL,15,1000,0,0,0,'t0')",
        (entry_id, event),
    )
    rows = []
    for slot, pid in enumerate(_STARTING_11, start=1):
        rows.append((entry_id, event, pid, slot, 2 if pid == captain_id else (1 if pid == vice_id else 1),
                     1 if pid == captain_id else 0, 1 if pid == vice_id else 0))
    for slot, pid in enumerate(_BENCH_4, start=12):
        rows.append((entry_id, event, pid, slot, 0, 0, 0))
    conn.executemany(
        "INSERT INTO my_team_picks (entry_id, event, player_id, squad_slot, multiplier, is_captain, "
        "is_vice_captain, active_chip, retrieved_at) VALUES (?,?,?,?,?,?,?,NULL,'t0')",
        rows,
    )
    conn.commit()


def test_no_source_returns_none(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    assert get_locked_squad(db_conn) is None
    assert is_locked(db_conn) is False


def test_real_synced_squad_is_preferred_source(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_real_picks(db_conn)

    locked = get_locked_squad(db_conn)

    assert locked is not None
    assert locked.source == "synced_real"
    assert locked.event == 1
    assert locked.squad_ids == frozenset(_FULL_15)
    assert {c.player_id for c in locked.xi.starting} == set(_STARTING_11)
    assert {c.player_id for c in locked.xi.bench} == set(_BENCH_4)
    assert locked.xi.captain.player_id == 30
    assert locked.xi.vice_captain.player_id == 20
    assert locked.bank_tenths == 15
    assert locked.decision_id is None
    assert is_locked(db_conn) is True


def test_xi_from_real_picks_handles_zero_picks_defensively(db_conn, caplog):
    """`_xi_from_real_picks` now takes already-fetched rows (see
    `get_latest_squad_detail`'s docstring for the real race this replaced) -
    the real call path (`get_locked_squad`) never passes an empty list, but
    a direct/future caller getting this wrong must still degrade cleanly,
    not crash."""
    import logging

    from fpl_agent.optimization.locked_squad import _xi_from_real_picks

    _seed(db_conn, budget_tenths=950, club_limit=4)

    with caplog.at_level(logging.WARNING, logger="fpl_agent.locked_squad"):
        result = _xi_from_real_picks(db_conn, event=2, entry_id=7378572, picks=[])

    assert result is None
    assert any("zero picks" in r.message for r in caplog.records)


def test_get_latest_squad_detail_is_one_atomic_read_not_two(db_conn):
    """Real regression guard for the 2026-08-29 fix: `get_locked_squad` used
    to call `get_latest_squad()` (one read) and then a SEPARATE
    `my_team_picks` query inside `_xi_from_real_picks` (a second read) -
    live-confirmed in production logs to race against the scheduler's own
    concurrent resync and intermittently report "no locked squad" despite
    real picks existing. `get_latest_squad_detail` is the real close: proves
    `get_locked_squad`'s only real path to `my_team_picks` is ONE query, by
    counting every SELECT issued against that table during a real call."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_real_picks(db_conn)

    # Scoped to the specific query that resolves event+squad_slot/captaincy
    # for XI-building (the one that used to run twice) - `get_locked_squad`
    # also queries `my_team_picks` separately for `compute_real_free_transfers`
    # (a different purpose, out of scope for this regression guard).
    queries_seen = []
    db_conn.set_trace_callback(
        lambda sql: queries_seen.append(sql) if "my_team_picks" in sql and "squad_slot" in sql else None
    )
    try:
        locked = get_locked_squad(db_conn)
    finally:
        db_conn.set_trace_callback(None)

    assert locked is not None
    assert len(queries_seen) == 1, f"expected exactly one squad_slot-detail query, got {len(queries_seen)}: {queries_seen}"


def test_a_pick_for_an_unresolved_player_is_skipped_not_fabricated(db_conn):
    """A real player id FPL reports that this project hasn't synced facts
    for yet (build_player_pool's own pool doesn't include it) must be
    skipped, never invented into a fabricated PlayerCandidate."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    set_my_team_entry_id(db_conn, 7378572)
    conn = db_conn
    conn.execute(
        "INSERT INTO my_team_gw_summary (entry_id, event, points, total_points, overall_rank, "
        "bank_tenths, team_value_tenths, event_transfers, event_transfers_cost, points_on_bench, retrieved_at) "
        "VALUES (7378572,1,0,0,NULL,10,1000,0,0,0,'t0')"
    )
    rows = [(7378572, 1, pid, slot, 1, 0, 0) for slot, pid in enumerate(_STARTING_11, start=1)]
    rows += [(7378572, 1, 99999, 12, 0, 0, 0)]  # unresolved id, not in the seeded pool
    rows += [(7378572, 1, pid, slot, 0, 0, 0) for slot, pid in enumerate(_BENCH_4[1:], start=13)]
    conn.executemany(
        "INSERT INTO my_team_picks (entry_id, event, player_id, squad_slot, multiplier, is_captain, "
        "is_vice_captain, active_chip, retrieved_at) VALUES (?,?,?,?,?,?,?,NULL,'t0')",
        rows,
    )
    conn.commit()

    locked = get_locked_squad(db_conn)

    assert locked is not None
    assert 99999 not in {c.player_id for c in locked.xi.starting + locked.xi.bench}


def test_null_squad_slot_defaults_to_bench_instead_of_crashing(db_conn):
    """Real regression test (2026-08-28, diagnosing an intermittent 'dashboard
    shows no squad' report): a genuinely malformed my_team_picks row with
    squad_slot=NULL used to crash _xi_from_real_picks on `None <= 11`, which
    propagated uncaught all the way through get_locked_squad() - one bad row
    silently taking down the whole locked-squad read. Must degrade to
    treating that one player as bench (logged, not fabricated as starting),
    never crash the read for the other 14 real picks."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    set_my_team_entry_id(db_conn, 7378572)
    conn = db_conn
    conn.execute(
        "INSERT INTO my_team_gw_summary (entry_id, event, points, total_points, overall_rank, "
        "bank_tenths, team_value_tenths, event_transfers, event_transfers_cost, points_on_bench, retrieved_at) "
        "VALUES (7378572,1,0,0,NULL,10,1000,0,0,0,'t0')"
    )
    rows = [(7378572, 1, pid, slot, 1, 0, 0) for slot, pid in enumerate(_STARTING_11[:-1], start=1)]
    rows += [(7378572, 1, _STARTING_11[-1], None, 1, 0, 0)]  # real malformed row: squad_slot=NULL
    rows += [(7378572, 1, pid, slot, 0, 0, 0) for slot, pid in enumerate(_BENCH_4, start=12)]
    conn.executemany(
        "INSERT INTO my_team_picks (entry_id, event, player_id, squad_slot, multiplier, is_captain, "
        "is_vice_captain, active_chip, retrieved_at) VALUES (?,?,?,?,?,?,?,NULL,'t0')",
        rows,
    )
    conn.commit()

    locked = get_locked_squad(db_conn)  # must not raise

    assert locked is not None
    assert len(locked.xi.starting) == 10  # the NULL-slot player didn't make the starting XI...
    assert _STARTING_11[-1] in {c.player_id for c in locked.xi.bench}  # ...it landed on the bench instead
    assert set(locked.squad_ids) == set(_FULL_15)  # every real pick still accounted for


def test_falls_back_to_locked_decision_when_no_real_sync_exists(db_conn, monkeypatch):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)
    log_decision(
        db_conn, "build_team", "locked", detail={
            "must_include_ids": [30, 20], "must_start_ids": [30], "exclude_ids": [], "gw_window": 1,
        },
    )

    locked = get_locked_squad(db_conn)

    assert locked is not None
    assert locked.source == "locked_decision"
    assert {30, 20} <= locked.squad_ids
    assert locked.bank_tenths is None
    assert locked.decision_id is not None


def test_an_unconstrained_locked_decision_is_not_treated_as_a_lock(db_conn, monkeypatch):
    """A build_team decision with no real must_include_ids at all (a bare,
    unconstrained run) isn't a genuine lock - falling back to it would defeat
    the whole point of this module (Mode A team-building shouldn't look
    "locked")."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)
    log_decision(
        db_conn, "build_team", "unconstrained", detail={
            "must_include_ids": [], "must_start_ids": [], "exclude_ids": [], "gw_window": 1,
        },
    )

    assert get_locked_squad(db_conn) is None
