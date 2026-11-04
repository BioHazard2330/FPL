"""
Backup/restore (section 112). Small rolling set, not "hundreds of local copies."
Uses sqlite3's own backup API (consistent snapshot, safe even mid-write) rather
than a raw file copy.
"""

import contextlib
import gzip
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    backups = sorted(BACKUP_DIR.glob("fpl_*.db"))
    while len(backups) > MAX_BACKUPS:
        backups.pop(0).unlink()


def list_backups() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []
    return sorted([*BACKUP_DIR.glob("fpl_*.db"), *BACKUP_DIR.glob("fpl_*.db.gz")], key=lambda p: p.name.split("_")[1][:15])


def create_compressed_backup(now: datetime | None = None) -> Path:
    """The daily backup: a consistent snapshot, verified, gzipped (200MB to about 48MB). Keeps the two newest and the newest
    that is at least a week old, so a problem noticed days later still has a good copy behind it."""
    now = now or datetime.now(timezone.utc)
    plain = create_backup()
    try:
        result = verify_backup(plain)
        if not result.ok:
            raise ValueError(f"backup failed verification: {result.detail}")
        dest = plain.with_suffix(".db.gz")
        with open(plain, "rb") as f, gzip.open(dest, "wb", compresslevel=6) as g:
            shutil.copyfileobj(f, g)
    finally:
        plain.unlink(missing_ok=True)
    _prune_compressed(now)
    return dest


def _prune_compressed(now: datetime) -> None:
    daily = sorted(BACKUP_DIR.glob("fpl_*.db.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    week_ago = (now - timedelta(days=7)).timestamp()
    keep = set(daily[:2]) | set([p for p in daily if p.stat().st_mtime <= week_ago][:1])
    for p in daily:
        if p not in keep:
            p.unlink()


def latest_backup_age_hours(now: datetime | None = None) -> float | None:
    now = now or datetime.now(timezone.utc)
    backups = list_backups()
    if not backups:
        return None
    return (now.timestamp() - max(p.stat().st_mtime for p in backups)) / 3600


@contextlib.contextmanager
def _as_database(path: Path):
    """The backup as a plain database file, decompressed to a temporary one if it is gzipped."""
    if path.suffix != ".gz":
        yield path
        return
    with tempfile.TemporaryDirectory(dir=BACKUP_DIR) as tmp:
        plain = Path(tmp) / "restore.db"
        with gzip.open(path, "rb") as g, open(plain, "wb") as f:
            shutil.copyfileobj(g, f)
        yield plain


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    detail: str


def verify_backup(path: Path) -> VerifyResult:
    if not path.exists():
        return VerifyResult(False, "file not found")
    try:
        with _as_database(path) as plain:
            conn = sqlite3.connect(plain)
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
    with _as_database(path) as plain:
        src, dest = sqlite3.connect(plain), sqlite3.connect(DB_PATH)
        try:
            src.backup(dest)  # through SQLite, so a write-ahead log beside the live file cannot survive into the restored one
        finally:
            src.close()
            dest.close()
    return pre_restore_backup
