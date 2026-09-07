from fpl_agent.ingestion.fotmob_results_backfill import backfill_match_results_from_fotmob
from fpl_agent.ingestion.market_identity import get_or_create_market_team


def _insert_team(conn, team_id: int, name: str, short: str):
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?, ?, ?, ?, 't0')",
        (team_id, team_id, name, short),
    )


def _insert_match(conn, fotmob_id: str, home_id: int, away_id: int, home_score: int, away_score: int,
                   kickoff: str, status: str = "FULL_TIME", competition: str = "Premier League"):
    conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "home_score, away_score, source, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?,'fotmob','t0')",
        (fotmob_id, competition, kickoff, home_id, away_id, status, home_score, away_score),
    )


def test_backfills_full_time_matches_for_the_given_season(db_conn):
    _insert_team(db_conn, 1, "Man City", "MCI")
    _insert_team(db_conn, 2, "Chelsea", "CHE")
    _insert_match(db_conn, "111", 1, 2, 2, 0, "2026-08-17T14:00:00.000Z")

    summary = backfill_match_results_from_fotmob(db_conn, "2026-27")

    assert summary["matches_inserted"] == 1
    row = db_conn.execute("SELECT * FROM match_results_history").fetchone()
    assert row["season"] == "2026-27"
    assert row["match_date"] == "2026-08-17"
    assert row["home_goals"] == 2
    assert row["away_goals"] == 0
    assert row["source"] == "fotmob_results"


def test_resolves_to_the_same_market_team_the_live_prediction_path_uses(db_conn):
    """Regression guard mirroring football_data_source.py's own equivalent
    test: this must resolve through get_or_create_market_team(conn, "fpl",
    ...) - the exact source string models/expected_points.py's live Dixon-
    Coles fixture lookups already use - so a fit trained on these rows lines
    up with the market_team_id the live path reads back, never a disconnected
    duplicate."""
    _insert_team(db_conn, 1, "Man City", "MCI")
    _insert_team(db_conn, 2, "Chelsea", "CHE")
    fpl_mci_id = get_or_create_market_team(db_conn, "fpl", "Man City")
    fpl_che_id = get_or_create_market_team(db_conn, "fpl", "Chelsea")

    _insert_match(db_conn, "111", 1, 2, 2, 0, "2026-08-17T14:00:00.000Z")
    backfill_match_results_from_fotmob(db_conn, "2026-27")

    row = db_conn.execute("SELECT home_team_id, away_team_id FROM match_results_history").fetchone()
    assert row["home_team_id"] == fpl_mci_id
    assert row["away_team_id"] == fpl_che_id


def test_skips_non_full_time_and_non_premier_league_matches(db_conn):
    _insert_team(db_conn, 1, "Man City", "MCI")
    _insert_team(db_conn, 2, "Chelsea", "CHE")
    _insert_match(db_conn, "111", 1, 2, None, None, "2026-08-17T14:00:00.000Z", status="LIVE")
    _insert_match(db_conn, "222", 1, 2, 3, 1, "2026-09-10T19:00:00.000Z", competition="EFL Cup")

    summary = backfill_match_results_from_fotmob(db_conn, "2026-27")

    assert summary["matches_inserted"] == 0
    assert db_conn.execute("SELECT COUNT(*) c FROM match_results_history").fetchone()["c"] == 0


def test_skips_matches_outside_the_season_window(db_conn):
    _insert_team(db_conn, 1, "Man City", "MCI")
    _insert_team(db_conn, 2, "Chelsea", "CHE")
    _insert_match(db_conn, "111", 1, 2, 1, 1, "2025-05-01T14:00:00.000Z")  # prior season

    summary = backfill_match_results_from_fotmob(db_conn, "2026-27")

    assert summary["matches_inserted"] == 0


def test_idempotent_on_rerun(db_conn):
    _insert_team(db_conn, 1, "Man City", "MCI")
    _insert_team(db_conn, 2, "Chelsea", "CHE")
    _insert_match(db_conn, "111", 1, 2, 2, 0, "2026-08-17T14:00:00.000Z")

    backfill_match_results_from_fotmob(db_conn, "2026-27")
    summary = backfill_match_results_from_fotmob(db_conn, "2026-27")

    assert summary["matches_inserted"] == 1
    assert db_conn.execute("SELECT COUNT(*) c FROM match_results_history").fetchone()["c"] == 1


def test_invalidates_the_dc_fit_cache(db_conn):
    from fpl_agent.models.expected_points import _get_or_fit_dc_model

    _insert_team(db_conn, 1, "Man City", "MCI")
    _insert_team(db_conn, 2, "Chelsea", "CHE")
    for i in range(10):
        _insert_match(db_conn, str(100 + i), 1, 2, 2, 1, f"2026-08-{10 + i:02d}T14:00:00.000Z")
    backfill_match_results_from_fotmob(db_conn, "2026-27")
    model_before = _get_or_fit_dc_model(db_conn, "2026-11-01")
    assert model_before is not None

    _insert_match(db_conn, "999", 1, 2, 1, 1, "2026-10-01T14:00:00.000Z")
    backfill_match_results_from_fotmob(db_conn, "2026-27")

    model_after = _get_or_fit_dc_model(db_conn, "2026-11-01")
    assert model_after is not model_before
