"""
fpl cleanup (sections 15, 111). Only ever touches raw payloads, temp files, and DB
free-space reclamation - never core tables (players, decisions, rules, user state).
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

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


def _prune_news(conn: sqlite3.Connection, retention_days: float) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    ids = [
        row["id"] for row in conn.execute(
            "SELECT id FROM news_items WHERE published_at IS NOT NULL AND published_at < ?",
            (cutoff,),
        ).fetchall()
    ]
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM news_item_players WHERE news_item_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM news_item_teams WHERE news_item_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM news_items WHERE id IN ({placeholders})", ids)
    conn.commit()
    return len(ids)


@dataclass(frozen=True)
class CleanupReport:
    raw_files_pruned: int
    temp_files_cleared: int
    vacuum_freed_mb: float
    news_items_pruned: int


MOMENTUM_KEEP_DAYS = 30


def thin_momentum(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """`player_transfer_momentum_history` takes a row per player per sync (877,000 rows, 77MB, by GW9). Past
    `MOMENTUM_KEEP_DAYS` keep what the price model reads for a night: each player's last snapshot before the 02:30 UTC run,
    his first after 03:00, and the day's last. The current row is never touched."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=MOMENTUM_KEEP_DAYS)).isoformat()
    n = conn.execute(
        """DELETE FROM player_transfer_momentum_history WHERE id IN (
            SELECT id FROM (
                SELECT id,
                    ROW_NUMBER() OVER (PARTITION BY player_id, substr(valid_from, 1, 10) ORDER BY valid_from DESC) AS day_last,
                    CASE WHEN substr(valid_from, 12, 5) < '02:30' THEN ROW_NUMBER() OVER (
                        PARTITION BY player_id, substr(valid_from, 1, 10), substr(valid_from, 12, 5) < '02:30' ORDER BY valid_from DESC) END AS before_run,
                    CASE WHEN substr(valid_from, 12, 5) >= '03:00' THEN ROW_NUMBER() OVER (
                        PARTITION BY player_id, substr(valid_from, 1, 10), substr(valid_from, 12, 5) >= '03:00' ORDER BY valid_from) END AS after_run
                FROM player_transfer_momentum_history WHERE valid_from < ? AND valid_until IS NOT NULL
            ) WHERE day_last > 1 AND COALESCE(before_run, 2) > 1 AND COALESCE(after_run, 2) > 1
        )""", (cutoff,),
    ).rowcount
    conn.commit()
    return n


def daily_maintenance(conn: sqlite3.Connection) -> dict:
    """The compressed backup first, then thinning, then giving the space back."""
    from fpl_agent.database.backup import create_compressed_backup

    path = create_compressed_backup()
    thinned = thin_momentum(conn)
    freed = _vacuum(conn) if thinned > 20000 else 0.0
    return {"backup": path.name, "backup_mb": round(path.stat().st_size / 1e6, 1), "momentum_rows_thinned": thinned, "freed_mb": freed}


def run_cleanup(conn: sqlite3.Connection) -> CleanupReport:
    budget = load_storage_budget()
    raw_pruned = prune_raw(budget.raw_retention_hours)
    temp_cleared = _clear_temp_dir()
    news_pruned = _prune_news(conn, budget.news_retention_days)
    freed_mb = _vacuum(conn)
    return CleanupReport(
        raw_files_pruned=raw_pruned, temp_files_cleared=temp_cleared,
        vacuum_freed_mb=freed_mb, news_items_pruned=news_pruned,
    )
