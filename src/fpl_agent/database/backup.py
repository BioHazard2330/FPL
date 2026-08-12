"""
Backup/restore (section 112). Small rolling set, not "hundreds of local copies."
Uses sqlite3's own backup API (consistent snapshot, safe even mid-write) rather
than a raw file copy.
"""

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fpl_agent.config import DATA_DIR, DB_PATH

BACKUP_DIR = DATA_DIR / "backups"
MAX_BACKUPS = 5


def create_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    # Microsecond resolution + collision fallback: two backups can legitimately
    # happen within the same second (e.g. restore_backup's safety-backup step
    # immediately followed by the actual restore) - a same-name collision would
    # silently overwrite the very file about to be restored from.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    dest = BACKUP_DIR / f"fpl_{stamp}.db"
    suffix = 0
    while dest.exists():
        suffix += 1
        dest = BACKUP_DIR / f"fpl_{stamp}_{suffix}.db"

    src_conn = sqlite3.connect(DB_PATH)
    dest_conn = sqlite3.connect(dest)
    try:
        src_conn.backup(dest_conn)
    finally:
        src_conn.close()
        dest_conn.close()

    _prune_old_backups()
    return dest


def _prune_old_backups() -> None:
    backups = list_backups()
    while len(backups) > MAX_BACKUPS:
        backups.pop(0).unlink()


def list_backups() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("fpl_*.db"))


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    detail: str


def verify_backup(path: Path) -> VerifyResult:
    if not path.exists():
        return VerifyResult(False, "file not found")
    try:
        conn = sqlite3.connect(path)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        migration_count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        conn.close()
    except Exception as e:
        return VerifyResult(False, str(e))

    if integrity != "ok":
        return VerifyResult(False, f"integrity_check failed: {integrity}")
    return VerifyResult(True, f"integrity ok, {migration_count} migration(s) applied")


def restore_backup(path: Path) -> Path:
    """Overwrites the live DB with `path`. Returns the path of a safety backup taken
    of the pre-restore state, in case the restore itself needs undoing."""
    if not path.exists():
        raise FileNotFoundError(path)
    result = verify_backup(path)
    if not result.ok:
        raise ValueError(f"refusing to restore - backup failed verification: {result.detail}")

    pre_restore_backup = create_backup()
    shutil.copy2(path, DB_PATH)
    return pre_restore_backup
