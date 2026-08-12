import os
import time

import fpl_agent.monitoring.cleanup as cleanup_mod
from fpl_agent.database.decisions import log_decision
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap


def _seed(conn, tmp_path, monkeypatch):
    bootstrap = make_bootstrap()
    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    log_decision(conn, "squad", "test decision", {"x": 1})
    conn.commit()

    db_path = tmp_path / "test.db"
    monkeypatch.setattr(cleanup_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cleanup_mod, "DB_PATH", db_path)

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stale_file = raw_dir / "stale_20200101T000000Z.json"
    stale_file.write_text("{}", encoding="utf-8")
    old_mtime = time.time() - 100 * 3600
    os.utime(stale_file, (old_mtime, old_mtime))
    monkeypatch.setattr("fpl_agent.ingestion.raw_store.RAW_DIR", raw_dir)

    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    (temp_dir / "scratch.tmp").write_text("junk", encoding="utf-8")

    return stale_file, temp_dir / "scratch.tmp"


def test_cleanup_clears_stale_raw_and_temp_files(db_conn, tmp_path, monkeypatch):
    stale_file, temp_file = _seed(db_conn, tmp_path, monkeypatch)

    report = cleanup_mod.run_cleanup(db_conn)

    assert report.raw_files_pruned == 1
    assert report.temp_files_cleared == 1
    assert not stale_file.exists()
    assert not temp_file.exists()


def test_cleanup_never_touches_core_tables(db_conn, tmp_path, monkeypatch):
    _seed(db_conn, tmp_path, monkeypatch)

    players_before = db_conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    decisions_before = db_conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]

    cleanup_mod.run_cleanup(db_conn)

    players_after = db_conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    decisions_after = db_conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]

    assert players_after == players_before == 1
    assert decisions_after == decisions_before == 1
