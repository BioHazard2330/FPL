import os
import time


def test_prune_raw_removes_only_expired(tmp_path, monkeypatch):
    monkeypatch.setattr("fpl_agent.ingestion.raw_store.RAW_DIR", tmp_path)
    from fpl_agent.ingestion.raw_store import prune_raw

    old_file = tmp_path / "old_20260101T000000Z.json"
    new_file = tmp_path / "new_20260101T000000Z.json"
    old_file.write_text("{}", encoding="utf-8")
    new_file.write_text("{}", encoding="utf-8")

    old_mtime = time.time() - 100 * 3600  # 100h ago
    os.utime(old_file, (old_mtime, old_mtime))

    deleted = prune_raw(retention_hours=72)

    assert deleted == 1
    assert not old_file.exists()
    assert new_file.exists()
