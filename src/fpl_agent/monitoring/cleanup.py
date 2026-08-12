"""
fpl cleanup (sections 15, 111). Only ever touches raw payloads, temp files, and DB
free-space reclamation - never core tables (players, decisions, rules, user state).
"""

import sqlite3
from dataclasses import dataclass

from fpl_agent.config import DATA_DIR, DB_PATH, load_storage_budget
from fpl_agent.ingestion.raw_store import prune_raw

def _clear_temp_dir() -> int:
    # Computed per-call (not at import time) so this reflects DATA_DIR at call
    # time, not whatever it was when the module first loaded.
    temp_dir = DATA_DIR / "tmp"
    if not temp_dir.exists():
        return 0
    cleared = 0
    for path in temp_dir.glob("*"):
        if path.is_file():
            path.unlink()
            cleared += 1
    return cleared


def _vacuum(conn: sqlite3.Connection) -> float:
    before_mb = DB_PATH.stat().st_size / (1024 * 1024) if DB_PATH.exists() else 0.0
    conn.execute("VACUUM")
    after_mb = DB_PATH.stat().st_size / (1024 * 1024) if DB_PATH.exists() else 0.0
    return round(max(0.0, before_mb - after_mb), 3)


@dataclass(frozen=True)
class CleanupReport:
    raw_files_pruned: int
    temp_files_cleared: int
    vacuum_freed_mb: float


def run_cleanup(conn: sqlite3.Connection) -> CleanupReport:
    budget = load_storage_budget()
    raw_pruned = prune_raw(budget.raw_retention_hours)
    temp_cleared = _clear_temp_dir()
    freed_mb = _vacuum(conn)
    return CleanupReport(raw_files_pruned=raw_pruned, temp_files_cleared=temp_cleared, vacuum_freed_mb=freed_mb)
