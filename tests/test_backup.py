import datetime as dt_module
import sqlite3

from fpl_agent.database import backup as backup_mod


def _seed_minimal_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE schema_migrations (filename TEXT PRIMARY KEY, applied_at TEXT)")
    conn.execute("INSERT INTO schema_migrations VALUES ('0001_x.sql','t0')")
    conn.execute("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO widgets (id, name) VALUES (1, 'original')")
    conn.commit()
    conn.close()


def _patch_paths(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(backup_mod, "DB_PATH", db_path)
    monkeypatch.setattr(backup_mod, "BACKUP_DIR", backup_dir)
    _seed_minimal_db(db_path)
    return db_path, backup_dir


def test_backup_then_verify_ok(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    path = backup_mod.create_backup()
    assert path.exists()
    result = backup_mod.verify_backup(path)
    assert result.ok
    assert "1 migration" in result.detail


def test_verify_missing_file_fails(tmp_path, monkeypatch):
    _, backup_dir = _patch_paths(tmp_path, monkeypatch)
    result = backup_mod.verify_backup(backup_dir / "does_not_exist.db")
    assert result.ok is False


def test_restore_brings_back_deleted_data(tmp_path, monkeypatch):
    db_path, _ = _patch_paths(tmp_path, monkeypatch)

    backup_path = backup_mod.create_backup()

    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM widgets WHERE id=1")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM widgets").fetchone()[0] == 0
    conn.close()

    safety_backup = backup_mod.restore_backup(backup_path)
    assert safety_backup.exists()

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT name FROM widgets WHERE id=1").fetchone()
    conn.close()
    assert row == ("original",)


def test_rolling_backup_set_prunes_oldest(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)

    counter = {"n": 0}

    class FakeDateTime:
        @staticmethod
        def now(tz=None):
            counter["n"] += 1
            return dt_module.datetime(2026, 1, 1, 0, 0, counter["n"] % 60, tzinfo=tz)

    monkeypatch.setattr(backup_mod, "datetime", FakeDateTime)

    for _ in range(backup_mod.MAX_BACKUPS + 2):
        backup_mod.create_backup()

    remaining = backup_mod.list_backups()
    assert len(remaining) == backup_mod.MAX_BACKUPS


def _point_at(monkeypatch, tmp_path):
    import sqlite3

    from fpl_agent.database import backup as b

    db = tmp_path / "live.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE schema_migrations (name TEXT)")
    c.execute("INSERT INTO schema_migrations VALUES ('x')")
    c.commit()
    c.close()
    monkeypatch.setattr(b, "DB_PATH", db)
    monkeypatch.setattr(b, "BACKUP_DIR", tmp_path / "backups")
    return b, db


def test_a_compressed_backup_verifies_and_restores(tmp_path, monkeypatch):
    import sqlite3

    b, db = _point_at(monkeypatch, tmp_path)
    path = b.create_compressed_backup()
    assert path.name.endswith(".db.gz") and b.verify_backup(path).ok
    c = sqlite3.connect(db)
    c.execute("DELETE FROM schema_migrations")
    c.commit()
    c.close()
    b.restore_backup(path)
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
    c.close()


def test_a_corrupt_compressed_backup_is_refused(tmp_path, monkeypatch):
    b, db = _point_at(monkeypatch, tmp_path)
    b.BACKUP_DIR.mkdir()
    bad = b.BACKUP_DIR / "fpl_20260101T000000.db.gz"
    bad.write_bytes(b"not a backup")
    assert not b.verify_backup(bad).ok


def test_rotation_keeps_the_two_newest_and_one_a_week_old(tmp_path, monkeypatch):
    import os
    from datetime import datetime, timezone

    b, db = _point_at(monkeypatch, tmp_path)
    b.BACKUP_DIR.mkdir()
    now = datetime(2026, 11, 20, tzinfo=timezone.utc)
    ages = [0, 1, 2, 3, 8, 9, 20]
    for days in ages:
        f = b.BACKUP_DIR / f"fpl_202611{20 - min(days, 19):02d}T000000.db.gz"
        f.write_bytes(b"x")
        t = now.timestamp() - days * 86400
        os.utime(f, (t, t))
    b._prune_compressed(now)
    left = sorted(round((now.timestamp() - p.stat().st_mtime) / 86400) for p in b.BACKUP_DIR.glob("*.gz"))
    assert left == [0, 1, 8]
