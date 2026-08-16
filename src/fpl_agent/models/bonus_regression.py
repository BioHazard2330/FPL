"""Shrinkage-regressed bonus-points-per-90 estimate. Reuses
player_regression.py::shrink_rate unmodified - it's generic, doesn't care
what stat it's shrinking. Reads player_season_history (season TOTALS,
"YYYY/YY"-format season_name from FPL's own history_past) rather than
player_match_stats_history (Understat, per-match) - Understat has no bonus
field, and BPS is FPL-proprietary, so season-total granularity is the only
granularity any of this project's sources have for bonus. before_season
filters strictly before that season_name string (lexicographic ordering
matches chronological ordering for this "YYYY/YY" format) for leakage-free
leave-one-season-out holdout validation - a season grain, not the match-grain
as_of_date the rest of the model layer uses, since that's the only grain
this data has. Never cross-reference against rules.season - that table uses
a different "YYYY-YY" convention entirely.
"""
import sqlite3

from fpl_agent.models.player_regression import ShrunkRate, shrink_rate


def position_average_bonus_per90(
    conn: sqlite3.Connection, position: str, before_season: str | None = None
) -> float:
    clause, params = ("AND psh.season_name < ?", (before_season,)) if before_season else ("", ())
    row = conn.execute(
        "SELECT SUM(psh.bonus) AS total, SUM(psh.minutes) AS minutes "
        "FROM player_season_history psh JOIN players p ON p.id = psh.player_id "
        "JOIN element_types et ON et.id = p.element_type "
        f"WHERE et.singular_name_short = ? AND psh.bonus IS NOT NULL AND psh.minutes IS NOT NULL {clause}",
        (position,) + params,
    ).fetchone()
    if not row or not row["minutes"]:
        return 0.0
    return (row["total"] or 0.0) / (row["minutes"] / 90)


def expected_bonus_per90(
    conn: sqlite3.Connection, player_id: int, before_season: str | None = None
) -> ShrunkRate:
    player = conn.execute(
        "SELECT et.singular_name_short AS position FROM players p "
        "JOIN element_types et ON et.id = p.element_type WHERE p.id=?",
        (player_id,),
    ).fetchone()
    if player is None:
        raise ValueError(f"unknown player_id: {player_id}")
    position = player["position"]

    clause, params = ("AND season_name < ?", (before_season,)) if before_season else ("", ())
    prior = conn.execute(
        "SELECT bonus, minutes FROM player_season_history "
        f"WHERE player_id=? AND bonus IS NOT NULL AND minutes IS NOT NULL {clause} "
        "ORDER BY season_name DESC LIMIT 1",
        (player_id,) + params,
    ).fetchone()
    player_total = prior["bonus"] if prior else 0.0
    player_minutes = prior["minutes"] if prior else 0

    position_avg = position_average_bonus_per90(conn, position, before_season)
    return shrink_rate(player_total, player_minutes, position_avg)
