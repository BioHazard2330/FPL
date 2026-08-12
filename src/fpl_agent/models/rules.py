import json
import sqlite3


def current_season(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT season FROM rules ORDER BY id DESC LIMIT 1").fetchone()
    return row["season"] if row else None


def get_rule(conn: sqlite3.Connection, season: str, rule_key: str, default=None):
    row = conn.execute(
        "SELECT value FROM rules WHERE rule_key=? AND season=? ORDER BY version DESC LIMIT 1",
        (rule_key, season),
    ).fetchone()
    return json.loads(row["value"]) if row else default
