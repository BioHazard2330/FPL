from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_chip_windows

_BOOTSTRAP = {
    "chips": [
        {"id": 1, "name": "wildcard", "number": 1, "start_event": 2, "stop_event": 19, "chip_type": "transfer"},
        {"id": 2, "name": "bboost", "number": 1, "start_event": 1, "stop_event": 19, "chip_type": "team"},
    ]
}


def test_chip_windows_sync_is_idempotent(db_conn):
    rows = normalize_chip_windows(_BOOTSTRAP, "2026-27")

    _upsert_many(db_conn, "chip_windows", rows, "t0")
    _upsert_many(db_conn, "chip_windows", rows, "t1")  # identical data again
    db_conn.commit()

    count = db_conn.execute("SELECT COUNT(*) AS c FROM chip_windows").fetchone()["c"]
    assert count == 2
