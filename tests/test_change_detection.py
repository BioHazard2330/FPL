from fpl_agent.ingestion.change_detection import (
    detect_player_lifecycle_changes,
    detect_setpiece_changes,
    snapshot_player_state,
    snapshot_setpiece_state,
)
from fpl_agent.ingestion.sync import _upsert_many, sync_setpiece_history
from fpl_agent.normalization.fpl_core import (
    normalize_element_types,
    normalize_players,
    normalize_teams,
)

from test_sync import make_bootstrap


def _seed(conn, bootstrap, now):
    _upsert_many(conn, "teams", normalize_teams(bootstrap), now)
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), now)
    _upsert_many(conn, "players", normalize_players(bootstrap), now)
    conn.commit()


def _events(conn):
    return conn.execute("SELECT event_type, severity, entity_id FROM change_events ORDER BY id").fetchall()


def test_new_player_detected(db_conn):
    bootstrap = make_bootstrap()
    prev = snapshot_player_state(db_conn)  # empty DB
    new_rows = normalize_players(bootstrap)
    _seed(db_conn, bootstrap, "t0")

    changed = detect_player_lifecycle_changes(db_conn, prev, new_rows, "t0", "fpl_api_bootstrap")
    db_conn.commit()

    assert changed == 1
    events = _events(db_conn)
    assert len(events) == 1
    assert events[0]["event_type"] == "new_player"


def test_no_events_when_nothing_changes(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    prev = snapshot_player_state(db_conn)
    new_rows = normalize_players(bootstrap)

    changed = detect_player_lifecycle_changes(db_conn, prev, new_rows, "t1", "fpl_api_bootstrap")
    db_conn.commit()

    assert changed == 0
    assert len(_events(db_conn)) == 0


def test_club_change_detected(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    prev = snapshot_player_state(db_conn)

    bootstrap2 = make_bootstrap()
    bootstrap2["teams"].append({
        "id": 2, "code": 4, "name": "Chelsea", "short_name": "CHE",
        "strength_overall_home": 4, "strength_overall_away": 4,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    bootstrap2["elements"][0]["team"] = 2
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap2), "t1")
    new_rows = normalize_players(bootstrap2)

    changed = detect_player_lifecycle_changes(db_conn, prev, new_rows, "t1", "fpl_api_bootstrap")
    db_conn.commit()

    assert changed == 1
    events = _events(db_conn)
    assert events[0]["event_type"] == "club_change"
    assert events[0]["severity"] == "HIGH"


def test_status_change_to_injured_is_high_severity(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    prev = snapshot_player_state(db_conn)

    bootstrap2 = make_bootstrap()
    bootstrap2["elements"][0]["status"] = "i"
    new_rows = normalize_players(bootstrap2)

    changed = detect_player_lifecycle_changes(db_conn, prev, new_rows, "t1", "fpl_api_bootstrap")
    db_conn.commit()

    assert changed == 1
    events = _events(db_conn)
    assert events[0]["event_type"] == "status_change"
    assert events[0]["severity"] == "HIGH"


def test_setpiece_change_detected_only_after_first_sync(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    bootstrap["elements"][0]["penalties_order"] = 1
    bootstrap["elements"][0]["penalties_text"] = "Primary"

    prev = snapshot_setpiece_state(db_conn)  # empty, first sync
    new_rows = [{
        "player_id": 1, "penalties_order": 1, "penalties_text": "Primary",
        "corners_order": None, "corners_text": None, "direct_fk_order": None, "direct_fk_text": None,
    }]
    sync_setpiece_history(db_conn, new_rows, "t0")
    changed = detect_setpiece_changes(db_conn, prev, new_rows, "t0", "fpl_api_bootstrap")
    db_conn.commit()
    assert changed == 0  # first observation isn't a "change"

    prev2 = snapshot_setpiece_state(db_conn)
    new_rows2 = [{
        "player_id": 1, "penalties_order": 2, "penalties_text": "Backup",
        "corners_order": None, "corners_text": None, "direct_fk_order": None, "direct_fk_text": None,
    }]
    sync_setpiece_history(db_conn, new_rows2, "t1")
    changed2 = detect_setpiece_changes(db_conn, prev2, new_rows2, "t1", "fpl_api_bootstrap")
    db_conn.commit()

    assert changed2 == 1
    events = _events(db_conn)
    assert events[0]["event_type"] == "setpiece_change"
    assert events[0]["severity"] == "HIGH"  # penalties_order 1 was involved
