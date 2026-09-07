"""Current-season Premier League match results for the Dixon-Coles fit,
sourced from this project's own already-synced FotMob match_intelligence
data instead of football-data.co.uk's CSV.

Real, confirmed 2026-09-07: football-data.co.uk returned a 503 on both its
CSV endpoint and its own site root (not a scraper bug - the site itself was
down), which meant `football_data_source.py::backfill_football_data` - the
sole source wiring live 2026-27 results into `match_results_history` every
`run-scheduled` cycle - silently stopped updating the live-season Dixon-Coles
fit. `match_intelligence` already carries every FULL_TIME match this project
discovers via `fpl sync-match` (source="fotmob", already the trusted, always-
OK status in `fpl source-status`) - deriving the current season's results
from data already being fetched anyway removes the external dependency
entirely for the live season, rather than adding a second scraper to fail
the same way. `football_data_source.py` is kept for its own real remaining
jobs (multi-season historical backfill, odds, Championship data for
promoted-team calibration) but is no longer wired into the automatic cycle -
see `cli/main.py::run_scheduled`.
"""
from datetime import datetime, timezone

from fpl_agent.ingestion.market_identity import get_or_create_market_team
from fpl_agent.ingestion.sync import update_source_health
from fpl_agent.models.expected_points import invalidate_dc_model_cache


def backfill_match_results_from_fotmob(conn, season: str) -> dict:
    """Upserts FULL_TIME Premier League `match_intelligence` rows for `season`
    (e.g. "2026-27") into `match_results_history`. Season boundary is July 1
    -> June 30, wide enough to cover the real PL calendar without pulling in
    an adjacent season. Idempotent (ON CONFLICT DO UPDATE), safe to call every
    cycle - real cost is a handful of already-cached SELECTs, no network call.
    Team names are resolved through `get_or_create_market_team(conn, "fpl",
    ...)` - the SAME source string `models/expected_points.py`'s own live
    Dixon-Coles fixture lookups use, so this always resolves to the identical
    `market_team_id` the live prediction path already reads, never a second,
    disconnected alias."""
    start_year = int(season.split("-")[0])
    start_date = f"{start_year}-07-01"
    end_date = f"{start_year + 1}-07-01"

    rows = conn.execute(
        "SELECT home_team_id, away_team_id, home_score, away_score, kickoff_utc "
        "FROM match_intelligence "
        "WHERE status='FULL_TIME' AND competition='Premier League' "
        "AND home_score IS NOT NULL AND away_score IS NOT NULL "
        "AND kickoff_utc >= ? AND kickoff_utc < ?",
        (start_date, end_date),
    ).fetchall()

    now = datetime.now(timezone.utc).isoformat()
    matches_inserted = 0
    for row in rows:
        home_name = conn.execute("SELECT name FROM teams WHERE id=?", (row["home_team_id"],)).fetchone()
        away_name = conn.execute("SELECT name FROM teams WHERE id=?", (row["away_team_id"],)).fetchone()
        if home_name is None or away_name is None:
            continue  # team no longer in the current teams table - defensive only, not expected for a PL fixture

        home_market_id = get_or_create_market_team(conn, "fpl", home_name["name"])
        away_market_id = get_or_create_market_team(conn, "fpl", away_name["name"])
        match_date = row["kickoff_utc"][:10]

        conn.execute(
            "INSERT INTO match_results_history "
            "(season, match_date, home_team_id, away_team_id, home_goals, away_goals, source, retrieved_at) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(season, match_date, home_team_id, away_team_id) DO UPDATE SET "
            "home_goals=excluded.home_goals, away_goals=excluded.away_goals, "
            "source=excluded.source, retrieved_at=excluded.retrieved_at",
            (season, match_date, home_market_id, away_market_id, row["home_score"], row["away_score"],
             "fotmob_results", now),
        )
        matches_inserted += 1

    conn.commit()
    if matches_inserted:
        invalidate_dc_model_cache(conn)

    update_source_health(conn, "fotmob_results", success=True, error=None)
    return {"matches_inserted": matches_inserted}
