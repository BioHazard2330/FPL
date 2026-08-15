"""Crosswalk between free-text team/player names used by external market-data
sources (football-data.co.uk, Understat) and this project's internal ids.
Necessary because external sources use plain names, and historical seasons
include teams (promoted/relegated) that aren't in the current `teams` table
at all - market_teams is a superset identity, only sometimes linked to a
current FPL team.
"""
import sqlite3


def _normalize(name: str) -> str:
    return " ".join(name.strip().lower().split())


def get_or_create_market_team(conn: sqlite3.Connection, source: str, source_name: str) -> int:
    alias = conn.execute(
        "SELECT market_team_id FROM team_name_aliases WHERE source=? AND source_name=?",
        (source, source_name),
    ).fetchone()
    if alias:
        return alias["market_team_id"]

    norm = _normalize(source_name)
    existing = conn.execute("SELECT id, canonical_name FROM market_teams").fetchall()
    for row in existing:
        if _normalize(row["canonical_name"]) == norm:
            market_team_id = row["id"]
            break
    else:
        fpl_team = conn.execute(
            "SELECT id FROM teams WHERE LOWER(name)=? OR LOWER(short_name)=?", (norm, norm)
        ).fetchone()
        cur = conn.execute(
            "INSERT INTO market_teams (canonical_name, fpl_team_id) VALUES (?, ?)",
            (source_name, fpl_team["id"] if fpl_team else None),
        )
        market_team_id = cur.lastrowid

    conn.execute(
        "INSERT OR IGNORE INTO team_name_aliases (market_team_id, source, source_name) VALUES (?, ?, ?)",
        (market_team_id, source, source_name),
    )
    conn.commit()
    return market_team_id


def resolve_player_id(conn: sqlite3.Connection, source: str, source_name: str) -> int | None:
    alias = conn.execute(
        "SELECT player_id FROM player_name_aliases WHERE source=? AND source_name=?",
        (source, source_name),
    ).fetchone()
    if alias:
        return alias["player_id"]

    norm = _normalize(source_name)
    match = conn.execute(
        "SELECT id FROM players WHERE LOWER(TRIM(first_name || ' ' || second_name))=? OR LOWER(web_name)=?",
        (norm, norm),
    ).fetchone()
    if match is None:
        return None

    conn.execute(
        "INSERT OR IGNORE INTO player_name_aliases (player_id, source, source_name) VALUES (?, ?, ?)",
        (match["id"], source, source_name),
    )
    conn.commit()
    return match["id"]
