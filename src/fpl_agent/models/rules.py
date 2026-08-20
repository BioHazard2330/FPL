import json
import sqlite3


def current_season(conn: sqlite3.Connection) -> str | None:
    """"Current season" means "what the live FPL API most recently reported" -
    scoped to source='fpl_api_bootstrap' rows specifically, not just whichever
    rule row happens to have the highest id. A plain `ORDER BY id DESC` breaks
    the moment any other source ever inserts a rules row for a different
    season (e.g. migrations/0017's real, sourced historical scoring rules for
    backtesting 2025-26) - confirmed live: right after that migration ran,
    this returned '2025-26' instead of '2026-27' on the real production DB,
    which would have silently corrupted every live command that calls this
    (fpl build-team/transfers/etc all read budget/club-limit/free-transfer
    rules through it)."""
    row = conn.execute(
        "SELECT season FROM rules WHERE source='fpl_api_bootstrap' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["season"] if row else None


def get_rule(conn: sqlite3.Connection, season: str, rule_key: str, default=None):
    row = conn.execute(
        "SELECT value FROM rules WHERE rule_key=? AND season=? ORDER BY version DESC LIMIT 1",
        (rule_key, season),
    ).fetchone()
    return json.loads(row["value"]) if row else default
