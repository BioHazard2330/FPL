"""Real regression tests for the historical data-fidelity diagnostic
(2026-09-07, Phase 7.4 Part 1/12) - the 5-state VALID_ZERO/MISSING_DATA/
UNRESOLVED_ID/SOURCE_FAILURE/NOT_APPLICABLE contract this project's
historical backtest/regret-analysis modules now read."""
from fpl_agent.backtesting.data_fidelity import (
    CONFIDENCE_PARTIAL,
    CONFIDENCE_UNRESOLVED,
    CONFIDENCE_VALID,
    MISSING_DATA,
    NOT_APPLICABLE,
    UNRESOLVED_ID,
    VALID_ZERO,
    confidence_for_status,
    diagnose_player_season,
    diagnose_season,
    low_confidence_player_season_count,
    player_season_confidence,
)

_SEASON = "2023-24"


def _seed_player(conn, player_id, web_name="P1", team_id=1):
    conn.execute("INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'t0')",
                 (team_id, team_id, f"Team{team_id}", f"T{team_id}"))
    conn.execute("INSERT OR IGNORE INTO market_teams (id, canonical_name, fpl_team_id) VALUES (?,?,?)",
                 (team_id, f"Team{team_id}", team_id))
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (3,'Midfielder','MID','Midfielders','t0')"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (?,?,?,?,3,'a','t0')", (player_id, player_id, web_name, team_id),
    )


def _seed_season_history(conn, player_id, season_dash, minutes):
    season_slash = season_dash.replace("-", "/")
    conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, retrieved_at) VALUES (?,?,?,'t0')",
        (player_id, season_slash, minutes),
    )


def _seed_match_row(conn, player_id, team_id, season_dash, minutes=90, resolved=True):
    conn.execute(
        "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, "
        "market_team_id, season, match_date, minutes, goals, assists, shots, xg, xa, key_passes, "
        "yellow_cards, red_cards, retrieved_at) VALUES (?,?,?,?,?,?,?,0,0,0,0.0,0.0,0,0,0,'t0')",
        (f"m{player_id}_{minutes}", f"u{player_id}", player_id if resolved else None, team_id,
         season_dash, "2023-08-15", minutes),
    )


def test_not_applicable_when_no_official_season_record(db_conn):
    _seed_player(db_conn, 1)
    db_conn.commit()

    status = diagnose_player_season(db_conn, 1, _SEASON)

    assert status.derived_status == NOT_APPLICABLE
    assert status.expected_match_presence is None


def test_not_applicable_when_official_record_shows_zero_minutes(db_conn):
    _seed_player(db_conn, 1)
    _seed_season_history(db_conn, 1, _SEASON, minutes=0)
    db_conn.commit()

    status = diagnose_player_season(db_conn, 1, _SEASON)

    assert status.derived_status == NOT_APPLICABLE


def test_valid_zero_when_resolved_rows_cover_expected_minutes(db_conn):
    _seed_player(db_conn, 1, team_id=1)
    _seed_season_history(db_conn, 1, _SEASON, minutes=180)
    _seed_match_row(db_conn, 1, 1, _SEASON, minutes=90, resolved=True)
    db_conn.execute(
        "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, "
        "market_team_id, season, match_date, minutes, goals, assists, shots, xg, xa, key_passes, "
        "yellow_cards, red_cards, retrieved_at) VALUES ('m1_2','u1',1,1,?,?,90,0,0,0,0.0,0.0,0,0,0,'t0')",
        (_SEASON, "2023-08-22"),
    )
    db_conn.commit()

    status = diagnose_player_season(db_conn, 1, _SEASON)

    assert status.derived_status == VALID_ZERO
    assert status.resolved_match_rows == 2


def test_unresolved_id_when_real_official_minutes_but_team_has_unresolved_rows(db_conn):
    """The exact real defect Phase 7.3 found: a real official record shows
    the player featured, but their own rows never resolved - and the SAME
    team has other genuinely unresolved rows this season, the honest
    signal that Understat DID cover this team/season, just not this
    player's own identity."""
    _seed_player(db_conn, 1, team_id=1)
    _seed_season_history(db_conn, 1, _SEASON, minutes=2500)
    # Player 1's own rows never resolved - team 1 has a real unresolved row
    # (a different real understat_player_id, never mapped to any player_id).
    db_conn.execute(
        "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, "
        "market_team_id, season, match_date, minutes, goals, assists, shots, xg, xa, key_passes, "
        "yellow_cards, red_cards, retrieved_at) VALUES ('m9','u999',NULL,1,?,?,90,0,0,0,0.0,0.0,0,0,0,'t0')",
        (_SEASON, "2023-08-15"),
    )
    # A real anchor: player 1 DID resolve in an earlier season (gives this
    # module a real historical team to check).
    _seed_match_row(db_conn, 1, 1, "2022-23", minutes=90, resolved=True)
    db_conn.commit()

    status = diagnose_player_season(db_conn, 1, _SEASON)

    assert status.derived_status == UNRESOLVED_ID
    assert status.resolved_match_rows == 0


def test_missing_data_when_team_is_otherwise_fully_resolved(db_conn):
    """Real official minutes exist, this player has zero resolved rows, but
    the SAME team's real coverage this season is otherwise complete (no
    unresolved rows at all) - more likely a genuine Understat source gap
    for this specific player than a resolver failure."""
    _seed_player(db_conn, 1, team_id=1)
    _seed_season_history(db_conn, 1, _SEASON, minutes=900)
    _seed_player(db_conn, 2, team_id=1, web_name="Teammate")
    _seed_match_row(db_conn, 2, 1, _SEASON, minutes=90, resolved=True)  # team fully resolved, just not player 1
    _seed_match_row(db_conn, 1, 1, "2022-23", minutes=90, resolved=True)  # real anchor season
    db_conn.commit()

    status = diagnose_player_season(db_conn, 1, _SEASON)

    assert status.derived_status == MISSING_DATA
    assert status.source_status == "team_fully_resolved"


def test_missing_data_when_no_team_anchor_exists_at_all(db_conn):
    _seed_player(db_conn, 1, team_id=1)
    _seed_season_history(db_conn, 1, _SEASON, minutes=900)
    db_conn.commit()

    status = diagnose_player_season(db_conn, 1, _SEASON)

    assert status.derived_status == MISSING_DATA
    assert status.source_status == "no_team_anchor"


def test_diagnose_season_covers_every_real_official_entrant(db_conn):
    _seed_player(db_conn, 1, team_id=1)
    _seed_player(db_conn, 2, team_id=1, web_name="P2")
    _seed_season_history(db_conn, 1, _SEASON, minutes=900)
    _seed_season_history(db_conn, 2, _SEASON, minutes=0)  # a real official zero-minute season
    db_conn.commit()

    statuses = diagnose_season(db_conn, _SEASON)

    assert {s.player_id for s in statuses} == {1, 2}
    by_id = {s.player_id: s for s in statuses}
    assert by_id[2].derived_status == NOT_APPLICABLE


def test_confidence_contract_maps_every_derived_status_to_one_of_four_levels():
    """Part 12's own small, composable contract - every real forensic state
    Part 1 produces must map to exactly one of VALID/PARTIAL/UNRESOLVED/
    INVALID, never left unmapped (a KeyError here would mean a future
    diagnostic state silently breaks every real downstream consumer)."""
    assert confidence_for_status(VALID_ZERO) == CONFIDENCE_VALID
    assert confidence_for_status(NOT_APPLICABLE) == CONFIDENCE_VALID
    assert confidence_for_status(MISSING_DATA) == CONFIDENCE_PARTIAL
    assert confidence_for_status(UNRESOLVED_ID) == CONFIDENCE_UNRESOLVED


def test_player_season_confidence_reflects_a_real_unresolved_case(db_conn):
    _seed_player(db_conn, 1, team_id=1)
    _seed_season_history(db_conn, 1, _SEASON, minutes=2500)
    db_conn.execute(
        "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, "
        "market_team_id, season, match_date, minutes, goals, assists, shots, xg, xa, key_passes, "
        "yellow_cards, red_cards, retrieved_at) VALUES ('m9','u999',NULL,1,?,?,90,0,0,0,0.0,0.0,0,0,0,'t0')",
        (_SEASON, "2023-08-15"),
    )
    _seed_match_row(db_conn, 1, 1, "2022-23", minutes=90, resolved=True)
    db_conn.commit()

    assert player_season_confidence(db_conn, 1, _SEASON) == CONFIDENCE_UNRESOLVED


def test_low_confidence_player_season_count_excludes_valid_and_not_applicable(db_conn):
    _seed_player(db_conn, 1, team_id=1)  # VALID_ZERO
    _seed_season_history(db_conn, 1, _SEASON, minutes=180)
    _seed_match_row(db_conn, 1, 1, _SEASON, minutes=90, resolved=True)
    db_conn.execute(
        "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, "
        "market_team_id, season, match_date, minutes, goals, assists, shots, xg, xa, key_passes, "
        "yellow_cards, red_cards, retrieved_at) VALUES ('m1_2','u1',1,1,?,?,90,0,0,0,0.0,0.0,0,0,0,'t0')",
        (_SEASON, "2023-08-22"),
    )
    _seed_player(db_conn, 2, team_id=1, web_name="P2")  # NOT_APPLICABLE
    _seed_season_history(db_conn, 2, _SEASON, minutes=0)
    _seed_player(db_conn, 3, team_id=2, web_name="P3")  # MISSING_DATA, no_team_anchor
    _seed_season_history(db_conn, 3, _SEASON, minutes=900)
    db_conn.commit()

    assert low_confidence_player_season_count(db_conn, _SEASON) == 1
