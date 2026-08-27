import json

from fpl_agent.database.decisions import log_decision
from fpl_agent.monitoring.live_snapshot import build_live_snapshot, write_live_snapshot


def _seed_event(conn, event_id=2, is_next=1, deadline_epoch=99999999999):
    conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, average_entry_score, highest_score, updated_at) VALUES "
        "(?,?,'t0',?,0,0,0,?,NULL,NULL,'t0')",
        (event_id, f"Gameweek {event_id}", deadline_epoch, is_next),
    )
    conn.commit()


def test_build_live_snapshot_has_no_rank_or_points_without_any_data(db_conn):
    _seed_event(db_conn)
    snap = build_live_snapshot(db_conn, live_payload=None)
    assert snap["rank"] is None
    assert snap["points"] is None
    assert snap["version"]  # a real, non-empty version stamp


def test_build_live_snapshot_reads_the_latest_live_rank_decision(db_conn):
    _seed_event(db_conn)
    log_decision(
        db_conn, "live_rank", summary="LiveFPL: rank ~123,456",
        detail={"source": "livefpl", "estimated_rank": 123456, "precision": "exact", "event": 2},
        confidence="high",
    )
    snap = build_live_snapshot(db_conn, live_payload=None)
    assert snap["rank"]["estimated_rank"] == 123456
    assert snap["rank"]["source"] == "livefpl"
    assert snap["rank"]["is_current"] is True  # event=2 matches the live/reference event


def test_build_live_snapshot_flags_a_stale_rank_as_not_current(db_conn):
    _seed_event(db_conn, event_id=2)
    _seed_event(db_conn, event_id=1, is_next=0)
    log_decision(
        db_conn, "live_rank", summary="stale GW1 rank",
        detail={"source": "livefpl", "estimated_rank": 999, "precision": "exact", "event": 1},
        confidence="high",
    )
    snap = build_live_snapshot(db_conn, live_payload=None)
    # A GW1 rank decision must never be presented as GW2's current rank -
    # same rule the dashboard's own rank tile already enforces.
    assert snap["rank"]["is_current"] is False


def test_write_live_snapshot_writes_real_json_to_disk(db_conn, tmp_path, monkeypatch):
    import fpl_agent.monitoring.live_snapshot as ls_mod

    target = tmp_path / "live_snapshot.json"
    monkeypatch.setattr(ls_mod, "SNAPSHOT_PATH", target)
    monkeypatch.setattr(ls_mod, "DATA_DIR", tmp_path)

    _seed_event(db_conn)
    path = write_live_snapshot(db_conn, live_payload=None)

    assert path == target
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["event"] == 2


def test_write_live_snapshot_never_fabricates_points_without_a_locked_squad(db_conn):
    _seed_event(db_conn)
    snap = build_live_snapshot(db_conn, live_payload={"elements": []})
    assert snap["points"] is None
