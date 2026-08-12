import sqlite3
from datetime import datetime, timezone

from fpl_agent.config import MIGRATIONS_DIR
from fpl_agent.database.connection import get_connection, transaction

_BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
)
"""


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(_BOOTSTRAP_SQL)
    conn.commit()


def applied_migrations(conn: sqlite3.Connection) -> set[str]:
    _ensure_migrations_table(conn)
    rows = conn.execute("SELECT filename FROM schema_migrations").fetchall()
    return {row["filename"] for row in rows}


def pending_migrations(conn: sqlite3.Connection) -> list[str]:
    applied = applied_migrations(conn)
    all_files = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    return [f for f in all_files if f not in applied]


def run_migrations(conn: sqlite3.Connection | None = None) -> list[str]:
    owns_conn = conn is None
    conn = conn or get_connection()
    applied_now = []
    try:
        for filename in pending_migrations(conn):
            sql = (MIGRATIONS_DIR / filename).read_text(encoding="utf-8")
            with transaction(conn):
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_migrations (filename, applied_at) VALUES (?, ?)",
                    (filename, datetime.now(timezone.utc).isoformat()),
                )
            applied_now.append(filename)
    finally:
        if owns_conn:
            conn.close()
    return applied_now
