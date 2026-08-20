"""Empirical-Bayes shrinkage of a player's per-90 goal/assist/xG/xA rate
toward the position-average rate, weighted by sample size (minutes played) -
a player with 1 match isn't as reliable a signal as one with 15.
PRIOR_STRENGTH_MATCHES is a fixed pseudo-sample-size, not fit to data yet -
same "flag the assumption" pattern as the rest of the model layer.
"""
import sqlite3
from dataclasses import dataclass

PRIOR_STRENGTH_MATCHES = 10


@dataclass(frozen=True)
class ShrunkRate:
    raw_per90: float
    shrunk_per90: float
    matches_played: float


def shrink_rate(player_total: float, player_minutes: int, position_avg_per90: float) -> ShrunkRate:
    matches = player_minutes / 90
    raw = (player_total / matches) if matches > 0 else 0.0
    shrunk = (matches * raw + PRIOR_STRENGTH_MATCHES * position_avg_per90) / (matches + PRIOR_STRENGTH_MATCHES)
    return ShrunkRate(raw_per90=round(raw, 4), shrunk_per90=round(shrunk, 4), matches_played=round(matches, 2))


def _date_clause(as_of_date: str | None) -> tuple[str, tuple]:
    return ("AND match_date < ?", (as_of_date,)) if as_of_date else ("", ())


_SUPPORTED_STATS = ("goals", "assists", "xg", "xa", "yellow_cards")


def position_average_per90(
    conn: sqlite3.Connection,
    position: str,
    stat: str,
    season: str,
    as_of_date: str | None = None,
) -> float:
    if stat not in _SUPPORTED_STATS:
        raise ValueError(f"unsupported stat: {stat}")
    clause, extra = _date_clause(as_of_date)
    row = conn.execute(
        f"SELECT SUM(pm.{stat}) AS total, SUM(pm.minutes) AS minutes "
        "FROM player_match_stats_history pm JOIN players p ON p.id = pm.player_id "
        "JOIN element_types et ON et.id = p.element_type "
        f"WHERE et.singular_name_short = ? AND pm.season = ? {clause}",
        (position, season) + extra,
    ).fetchone()
    if not row or not row["minutes"]:
        return 0.0
    return (row["total"] or 0.0) / (row["minutes"] / 90)


def player_shrunk_rates(conn: sqlite3.Connection, player_id: int, season: str, as_of_date: str | None = None) -> dict:
    player = conn.execute(
        "SELECT et.singular_name_short AS position FROM players p "
        "JOIN element_types et ON et.id = p.element_type WHERE p.id=?", (player_id,),
    ).fetchone()
    if player is None:
        raise ValueError(f"unknown player_id: {player_id}")
    position = player["position"]

    clause, extra = _date_clause(as_of_date)
    row = conn.execute(
        "SELECT SUM(goals) AS goals, SUM(assists) AS assists, SUM(xg) AS xg, SUM(xa) AS xa, "
        "SUM(yellow_cards) AS yellow_cards, SUM(minutes) AS minutes "
        f"FROM player_match_stats_history WHERE player_id=? AND season=? {clause}",
        (player_id, season) + extra,
    ).fetchone()
    minutes = (row["minutes"] or 0) if row else 0

    result = {}
    for stat in _SUPPORTED_STATS:
        total = (row[stat] if row else 0) or 0.0
        prior = position_average_per90(conn, position, stat, season, as_of_date)
        key = "cards" if stat == "yellow_cards" else stat
        result[key] = shrink_rate(total, minutes, prior)
    return result


_SEASON_FALLBACK_COLUMNS = ("goals_scored", "expected_assists")


def season_position_average_per90(
    conn: sqlite3.Connection, position: str, column: str, before_season: str | None = None
) -> float:
    """Same population-prior computation as position_average_per90, but off
    player_season_history (season TOTALS, "YYYY/YY" season_name) instead of
    player_match_stats_history (Understat, per-match) - see season_shrunk_rate's
    docstring for why this exists. `column` is whitelisted, not user input, but
    validated anyway since it's interpolated into the query (no parameterized-
    identifier support in sqlite3)."""
    if column not in _SEASON_FALLBACK_COLUMNS:
        raise ValueError(f"unsupported season fallback column: {column}")
    clause, params = ("AND psh.season_name < ?", (before_season,)) if before_season else ("", ())
    row = conn.execute(
        f"SELECT SUM(psh.{column}) AS total, SUM(psh.minutes) AS minutes "
        "FROM player_season_history psh JOIN players p ON p.id = psh.player_id "
        "JOIN element_types et ON et.id = p.element_type "
        f"WHERE et.singular_name_short = ? AND psh.{column} IS NOT NULL AND psh.minutes IS NOT NULL {clause}",
        (position,) + params,
    ).fetchone()
    if not row or not row["minutes"]:
        return 0.0
    return (row["total"] or 0.0) / (row["minutes"] / 90)


def season_shrunk_rate(
    conn: sqlite3.Connection, player_id: int, column: str, before_season: str | None = None
) -> ShrunkRate:
    """Fallback for when player_match_stats_history (Understat, per-match shot
    data) has zero rows for a player - a real, current condition (Understat's
    page structure changed, fpl backfill-xg is broken, confirmed 0 rows
    reachable in a fresh sync as of 2026-08-20 - see CLAUDE.md). Without this,
    player_shrunk_rates' goals/xa components silently collapse to 0.0 for
    EVERY player (both the player's own raw rate AND the shrinkage prior come
    from the same empty table, so shrink_rate(0, 0, 0) = 0) - not a "slightly
    conservative estimate", a complete, silent loss of the single largest
    scoring component in live projections. Reuses shrink_rate() unmodified
    over player_season_history instead, exactly the same empirical-Bayes
    treatment bonus_regression.py already established for bonus points (same
    season-grain limitation: no source this project has carries shot-level
    goals/assists data outside Understat, so this can't be match-grain like
    the primary path when it's actually working). Column choice matches the
    existing live-Understat design's own asymmetry (see expected_points.py):
    goals uses the player's own ACTUAL goals_scored (real outcomes, not
    predicted), assists uses the official expected_assists (xA is treated as
    the more stable predictor for assists specifically, same reasoning
    Pillar 0 already applied when both were available from Understat)."""
    player = conn.execute(
        "SELECT et.singular_name_short AS position FROM players p "
        "JOIN element_types et ON et.id = p.element_type WHERE p.id=?",
        (player_id,),
    ).fetchone()
    if player is None:
        raise ValueError(f"unknown player_id: {player_id}")
    position = player["position"]

    clause, params = ("AND season_name < ?", (before_season,)) if before_season else ("", ())
    row = conn.execute(
        f"SELECT {column}, minutes FROM player_season_history "
        f"WHERE player_id=? AND {column} IS NOT NULL AND minutes IS NOT NULL {clause} "
        "ORDER BY season_name DESC LIMIT 1",
        (player_id,) + params,
    ).fetchone()
    player_total = row[column] if row else 0.0
    player_minutes = row["minutes"] if row else 0

    position_avg = season_position_average_per90(conn, position, column, before_season)
    return shrink_rate(player_total, player_minutes, position_avg)


def player_share_of_team_xg(
    conn: sqlite3.Connection, player_id: int, market_team_id: int, season: str, as_of_date: str | None = None
) -> float:
    clause, extra = _date_clause(as_of_date)
    player_xg = conn.execute(
        f"SELECT SUM(xg) AS total FROM player_match_stats_history WHERE player_id=? AND season=? {clause}",
        (player_id, season) + extra,
    ).fetchone()["total"] or 0.0
    team_xg = conn.execute(
        f"SELECT SUM(xg) AS total FROM player_match_stats_history WHERE market_team_id=? AND season=? {clause}",
        (market_team_id, season) + extra,
    ).fetchone()["total"] or 0.0
    return player_xg / team_xg if team_xg else 0.0
