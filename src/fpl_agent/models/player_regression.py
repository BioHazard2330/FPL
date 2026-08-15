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
