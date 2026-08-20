"""How much of a team's contributing squad from last season is no longer at
the club - a real, computable signal (no new external source) for how much
to trust that team's historical Dixon-Coles fit before real matches exist
this season to re-earn that trust. Uses player_match_stats_history
(Understat, market_team_id per match) for "who actually played meaningful
minutes for this club last season" and the current players table for "who's
still there" - both already synced by this project.

This is a documented heuristic (see docs/superpowers/specs/2026-08-20-
preseason-calibration-design.md), not fit to real data - there is no
in-season 2026-27 evidence yet to validate the shrink strength against, same
honesty posture as models/price_forecast.py."""
import sqlite3

from fpl_agent.ingestion.market_identity import get_or_create_market_team
from fpl_agent.models.rules import current_season

MIN_CONTRIBUTOR_MINUTES = 450  # ~5 full matches - a real, minutes-weighted contributor, not a cameo

# Keyed by (id(conn), team_id, season); the connection itself is stored
# alongside the ratio so its id() can't be recycled into a false cache hit
# after it's garbage-collected - same reasoning as expected_points.py's
# _dc_model_cache.
_churn_cache: dict[tuple[int, int, str], tuple[sqlite3.Connection, float | None]] = {}


def prior_season(season: str) -> str:
    """'2026-27' -> '2025-26'."""
    start = int(season.split("-")[0]) - 1
    return f"{start}-{str(start + 1)[-2:]}"


def team_churn_ratio(conn: sqlite3.Connection, team_id: int, season: str | None = None) -> float | None:
    """Minutes-weighted fraction of last season's meaningful contributors for
    `team_id` who are no longer registered there this season. Returns None
    (not 0.0) when there isn't enough history to compute this honestly -
    covers genuinely promoted teams (no Understat EPL row for them last
    season) and any team missing a backfill, rather than fabricating a
    "zero churn" reading."""
    season = season or current_season(conn)
    if season is None:
        return None
    key = (id(conn), team_id, season)
    if key in _churn_cache:
        return _churn_cache[key][1]

    team_row = conn.execute("SELECT name FROM teams WHERE id=?", (team_id,)).fetchone()
    if team_row is None:
        _churn_cache[key] = (conn, None)
        return None
    market_team_id = get_or_create_market_team(conn, "fpl", team_row["name"])

    last_season = prior_season(season)
    # player_id IS NOT NULL: rows where the Understat->FPL crosswalk never
    # resolved a name (fringe/loan/departed players never entering this
    # season's `players` table) must be excluded before GROUP BY - SQL groups
    # all NULLs together into one artificial "contributor", so dozens of
    # genuinely separate sub-threshold cameo appearances silently sum past
    # MIN_CONTRIBUTOR_MINUTES as a single phantom entry. Confirmed live: this
    # inflated Man City's churn ratio to 0.60 (a single NULL-id blob carrying
    # 21520 of the team's 36733 total contributor-minutes) when the real
    # figure, once excluded, is ~0.03 (just Bobb's departure).
    contributors = conn.execute(
        "SELECT player_id, SUM(minutes) AS mins FROM player_match_stats_history "
        "WHERE market_team_id=? AND season=? AND player_id IS NOT NULL "
        "GROUP BY player_id HAVING SUM(minutes) >= ?",
        (market_team_id, last_season, MIN_CONTRIBUTOR_MINUTES),
    ).fetchall()
    if not contributors:
        _churn_cache[key] = (conn, None)
        return None

    total_minutes = departed_minutes = 0
    for row in contributors:
        total_minutes += row["mins"]
        current = conn.execute(
            "SELECT team_id, removed FROM players WHERE id=?", (row["player_id"],)
        ).fetchone()
        if current is None or current["removed"] or current["team_id"] != team_id:
            departed_minutes += row["mins"]

    ratio = departed_minutes / total_minutes
    _churn_cache[key] = (conn, ratio)
    return ratio
