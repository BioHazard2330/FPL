import pytest

from fpl_agent.backtesting.decision_regret import classify_transfer_regret, decompose_season_regret
from fpl_agent.backtesting.season_backtest import SeasonBacktestResult, TransferLogEntry

_SEASON = "2025-26"  # real historical scoring rules already seeded by migration 0017 on every fresh test DB


def _seed_base(conn, element_type_id=3, position="MID"):
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Team A','TMA','t0')")
    conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (1, 'Team A', 1)")
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (?,?,?,?, 't0')",
        (element_type_id, position, position, position),
    )


def _seed_player(conn, player_id, element_type_id=3):
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (?,?,?,1,?,'a','t0')",
        (player_id, player_id, f"P{player_id}", element_type_id),
    )


def _seed_match(conn, player_id, match_date, minutes, goals=0, assists=0):
    conn.execute(
        "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, "
        "market_team_id, season, match_date, minutes, goals, assists, shots, xg, xa, key_passes, "
        "yellow_cards, red_cards, retrieved_at) VALUES (?,?,?,1,?,?,?,?,?,0,0.0,0.0,0,0,0,'t0')",
        (f"m{player_id}_{match_date}", f"u{player_id}", player_id, _SEASON, match_date, minutes, goals, assists),
    )


def _entry(out_id, in_id, round_start="2025-08-15", round_end="2025-08-22"):
    return TransferLogEntry(
        round_idx=0, round_start=round_start, round_end=round_end,
        player_out_id=out_id, player_out_name=f"P{out_id}", player_in_id=in_id, player_in_name=f"P{in_id}",
        predicted_gain=3.0,
    )


def test_classify_transfer_regret_labels_minutes_error(db_conn):
    """Real, disclosed-scope classification (Phase 7.3 Part 8): the IN player
    barely playing while the OUT player would have started is the one
    category this simplified single-scalar-xp backtest can cleanly attribute
    to an appearance shortfall rather than a rate-underperformance."""
    _seed_base(db_conn)
    _seed_player(db_conn, 1)
    _seed_player(db_conn, 2)
    _seed_match(db_conn, 1, "2025-08-16", minutes=90, goals=1)  # out player started and scored
    _seed_match(db_conn, 2, "2025-08-16", minutes=5)  # in player barely played
    db_conn.commit()

    c = classify_transfer_regret(db_conn, _SEASON, _entry(out_id=1, in_id=2))

    assert c.category == "MINUTES_ERROR"
    assert c.regret > 0


def test_classify_transfer_regret_labels_data_error(db_conn):
    """No real match_stats row at all for the in-player this round (not even
    a low-minutes one) - a genuine data gap, never conflated with a real
    zero-minutes appearance."""
    _seed_base(db_conn)
    _seed_player(db_conn, 1)
    _seed_player(db_conn, 2)
    _seed_match(db_conn, 1, "2025-08-16", minutes=90, goals=1)
    db_conn.commit()

    c = classify_transfer_regret(db_conn, _SEASON, _entry(out_id=1, in_id=2))

    assert c.category == "DATA_ERROR"


def test_classify_transfer_regret_detects_data_error_via_confidence_even_with_a_resolved_round_row(db_conn):
    """A real, more subtle DATA_ERROR the old `in_had_data`-only heuristic
    could never see (Phase 7.4 Part 12): the in-player has a real resolved
    row for the SPECIFIC scored round (so `in_had_data` alone would call
    this a false PROJECTION_ERROR), but their season-level identity
    resolution is a known, confirmed UNRESOLVED_ID case per the shared
    `data_fidelity` contract - the same real bug shape Part 9's Gabriel
    Magalhães/Gabriel Jesus collision was (a handful of rows resolve while
    most of a season's real coverage for that identity doesn't)."""
    _seed_base(db_conn)
    _seed_player(db_conn, 1)
    _seed_player(db_conn, 2)
    _seed_match(db_conn, 1, "2025-08-16", minutes=90, goals=1)  # out player scored
    _seed_match(db_conn, 2, "2025-08-16", minutes=90)  # in player: one real resolved round row, no goals
    # Real official season record shows ~2500 minutes for this player this
    # season - far more than the single resolved row above - and the same
    # team carries another genuinely unresolved row, the real UNRESOLVED_ID
    # signal `data_fidelity.diagnose_player_season` is built to catch.
    db_conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, retrieved_at) "
        "VALUES (2,'2025/26',2500,'t0')"
    )
    db_conn.execute(
        "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, "
        "market_team_id, season, match_date, minutes, goals, assists, shots, xg, xa, key_passes, "
        "yellow_cards, red_cards, retrieved_at) VALUES ('m9','u999',NULL,1,?,?,90,0,0,0,0.0,0.0,0,0,0,'t0')",
        (_SEASON, "2025-08-23"),
    )
    db_conn.commit()

    c = classify_transfer_regret(db_conn, _SEASON, _entry(out_id=1, in_id=2))

    assert c.category == "DATA_ERROR"


def test_classify_transfer_regret_labels_projection_error(db_conn):
    """Both players played a genuine full match - the in-player just scored
    less. Not an appearance/data problem, a real rate-projection miss."""
    _seed_base(db_conn)
    _seed_player(db_conn, 1)
    _seed_player(db_conn, 2)
    _seed_match(db_conn, 1, "2025-08-16", minutes=90, goals=1)
    _seed_match(db_conn, 2, "2025-08-16", minutes=90)
    db_conn.commit()

    c = classify_transfer_regret(db_conn, _SEASON, _entry(out_id=1, in_id=2))

    assert c.category == "PROJECTION_ERROR"


def test_classify_transfer_regret_not_a_regret_when_the_swap_paid_off(db_conn):
    _seed_base(db_conn)
    _seed_player(db_conn, 1)
    _seed_player(db_conn, 2)
    _seed_match(db_conn, 1, "2025-08-16", minutes=90)
    _seed_match(db_conn, 2, "2025-08-16", minutes=90, goals=1)  # in player outscored out player
    db_conn.commit()

    c = classify_transfer_regret(db_conn, _SEASON, _entry(out_id=1, in_id=2))

    assert c.category == "NOT_A_REGRET"
    assert c.regret <= 0


def test_decompose_season_regret_ranks_by_total_regret_and_excludes_non_regrets(db_conn):
    """3 real transfers: one MINUTES_ERROR (larger regret), one
    PROJECTION_ERROR (smaller regret), one that paid off (excluded
    entirely) - the largest recurring source of regret must rank first,
    matching spec Part 8's "find the largest recurring source of regret"."""
    _seed_base(db_conn)
    for pid in (1, 2, 3, 4, 5, 6):
        _seed_player(db_conn, pid)
    # Transfer A: MINUTES_ERROR, regret = 9 - 0 = 9 (2 goals * ~5pt MID rate roughly, real seeded rate)
    _seed_match(db_conn, 1, "2025-08-16", minutes=90, goals=2)
    _seed_match(db_conn, 2, "2025-08-16", minutes=3)
    # Transfer B: PROJECTION_ERROR, regret smaller (both played, out scored 1 more goal)
    _seed_match(db_conn, 3, "2025-08-16", minutes=90, goals=1)
    _seed_match(db_conn, 4, "2025-08-16", minutes=90)
    # Transfer C: paid off, must be excluded from the decomposition entirely
    _seed_match(db_conn, 5, "2025-08-16", minutes=90)
    _seed_match(db_conn, 6, "2025-08-16", minutes=90, goals=1)
    db_conn.commit()

    result = SeasonBacktestResult(
        season=_SEASON, rounds_evaluated=1, decision_total_points=0.0, static_total_points=0.0,
        transfers_made=3, delta_vs_static=0.0,
        transfer_log=[_entry(1, 2), _entry(3, 4), _entry(5, 6)],
    )

    decomposed = decompose_season_regret(db_conn, _SEASON, result)

    assert "NOT_A_REGRET" not in decomposed
    assert set(decomposed) == {"MINUTES_ERROR", "PROJECTION_ERROR"}
    assert decomposed["MINUTES_ERROR"][0] == 1
    # Largest recurring source of regret ranks first.
    categories_by_rank = list(decomposed)
    assert categories_by_rank[0] == "MINUTES_ERROR"
    assert decomposed["MINUTES_ERROR"][1] > decomposed["PROJECTION_ERROR"][1]
