import sqlite3
from contextlib import contextmanager

from fpl_agent.config import DATA_DIR, DB_PATH


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # timeout=30 (2026-08-29, same "dashboard randomly shows no squad"
    # investigation as ingestion/my_team.py::get_latest_squad's own atomicity
    # fix) - this project runs a real concurrent writer (the Windows Task
    # Scheduler's own `run-scheduled`, independent of any interactive
    # session) against this same real database file. The Python default
    # (5s) is short enough that a slow real write (a network-bound sync step
    # holding a transaction open) could genuinely make a concurrent reader
    # hit `sqlite3.OperationalError: database is locked` rather than simply
    # waiting - a real, disclosed defensive hardening, not proof this was
    # the exact mechanism behind the reported incident (the confirmed root
    # cause was the separate torn-read fix in get_latest_squad).
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
