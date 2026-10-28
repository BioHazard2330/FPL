import json
import sqlite3
import time

import fpl_agent.live.payload_snapshots as snap


def _factory(path):
    def make():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c
    c = make()
    c.execute("CREATE TABLE payload_snapshot (screen TEXT PRIMARY KEY, body TEXT NOT NULL, built_at TEXT NOT NULL, build_seconds REAL)")
    c.commit()
    c.close()
    return make


def test_first_request_builds_then_serves_the_copy_and_survives_a_restart(tmp_path):
    snap.clear_memory()
    factory = _factory(tmp_path / "s.db")
    calls = []

    def build(conn):
        calls.append(1)
        return {"n": len(calls)}

    assert json.loads(snap.serve("scout", build, factory)) == {"n": 1}
    assert json.loads(snap.serve("scout", build, factory)) == {"n": 1}
    assert len(calls) == 1
    snap.clear_memory()
    assert json.loads(snap.serve("scout", build, factory))["n"] == 1
    assert len(calls) == 1


def test_a_stale_copy_is_served_at_once_and_rebuilt_behind_it(tmp_path, monkeypatch):
    snap.clear_memory()
    factory = _factory(tmp_path / "s.db")
    monkeypatch.setattr(snap, "FRESH_SECONDS", -1.0)
    calls = []

    def build(conn):
        calls.append(1)
        return {"n": len(calls)}

    snap.serve("advanced", build, factory)
    stale = json.loads(snap.serve("advanced", build, factory))
    assert stale["n"] == 1 and "_snapshot_age_seconds" in stale
    for _ in range(400):
        if len(calls) == 2 and "advanced" not in snap._building and json.loads(snap._memory["advanced"][0])["n"] == 2:
            break
        time.sleep(0.05)
    assert json.loads(snap._memory["advanced"][0])["n"] == 2
