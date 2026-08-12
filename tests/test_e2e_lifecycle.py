"""
Section 106 end-to-end test: proves the phases actually compose, not just work
in isolation. Uses synthetic data (no live network) - squad build -> decision
journal -> captaincy -> chips -> transfers -> backup -> cleanup -> restore.
"""

import sqlite3

import fpl_agent.database.backup as backup_mod
import fpl_agent.monitoring.cleanup as cleanup_mod
from fpl_agent.database.decisions import get_decision, log_decision
from fpl_agent.optimization.captaincy import captaincy_report
from fpl_agent.optimization.chips import bench_boost_value, eligible_chips
from fpl_agent.optimization.squad import optimise_squad, pick_starting_xi
from fpl_agent.optimization.transfers import recommend

from test_optimization_squad import _patch_expected_points, _seed as seed_squad_pool


def test_full_lifecycle_composes_without_error(db_conn, tmp_path, monkeypatch):
    seed_squad_pool(db_conn, budget_tenths=950, club_limit=4)
    _patch_expected_points(monkeypatch)

    # squad optimisation
    result = optimise_squad(db_conn, n_gw=1)
    assert result.status == "Optimal"
    xi = pick_starting_xi(db_conn, result.squad)
    assert xi.captain is not None
    squad_ids = [c.player_id for c in result.squad]

    # decision journal
    decision_id = log_decision(
        db_conn, "squad", "e2e test squad", {"total_xp": result.total_xp}, model_version="test"
    )
    assert get_decision(db_conn, decision_id).decision_type == "squad"

    # captaincy
    cap_report = captaincy_report(db_conn, squad_ids)
    assert cap_report.best is not None

    # chips
    eligible_chips(db_conn, event=1)  # empty chip_windows table - must not crash
    bb_value = bench_boost_value(db_conn, squad_ids)
    assert isinstance(bb_value, float)

    # transfers - zero-signal synthetic data means "roll" is the correct, valid outcome
    rec = recommend(db_conn, squad_ids, bank_tenths=0, free_transfers=1, n_gw=3)
    assert rec.action in ("roll", "transfer")

    # backup
    db_path = tmp_path / "test.db"
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(backup_mod, "DB_PATH", db_path)
    monkeypatch.setattr(backup_mod, "BACKUP_DIR", backup_dir)
    backup_path = backup_mod.create_backup()
    assert backup_mod.verify_backup(backup_path).ok

    # cleanup - must never touch core tables
    monkeypatch.setattr(cleanup_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cleanup_mod, "DB_PATH", db_path)
    monkeypatch.setattr("fpl_agent.ingestion.raw_store.RAW_DIR", tmp_path / "raw")
    players_before = db_conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    decisions_before = db_conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    cleanup_mod.run_cleanup(db_conn)
    assert db_conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == players_before
    assert db_conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == decisions_before

    # restore round-trip (restoring from a backup taken of the same state - a no-op on data)
    db_conn.close()  # release the file lock before a file-level restore
    backup_mod.restore_backup(backup_path)

    reopened = sqlite3.connect(db_path)
    reopened.row_factory = sqlite3.Row
    assert reopened.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == decisions_before
    assert reopened.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    reopened.close()
