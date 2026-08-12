import json
import sqlite3

_SETPIECE_FIELDS = ("penalties_order", "penalties_text", "corners_order", "corners_text", "direct_fk_order", "direct_fk_text")

_BAD_STATUS = {"i", "s", "u"}  # injured, suspended, unavailable


def _status_severity(prev_status: str, new_status: str) -> str:
    if new_status in _BAD_STATUS:
        return "HIGH"
    if new_status == "d":
        return "MEDIUM"
    if prev_status in _BAD_STATUS and new_status == "a":
        return "MEDIUM"
    return "LOW"


def _setpiece_severity(old: tuple, new: tuple) -> str:
    return "HIGH" if old[0] == 1 or new[0] == 1 else "MEDIUM"


def record_event(
    conn: sqlite3.Connection,
    event_type: str,
    entity: str,
    entity_id: int,
    old_value,
    new_value,
    detected_at: str,
    source: str,
    confidence: str,
    severity: str,
    fpl_impact: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO change_events "
        "(event_type, entity, entity_id, old_value, new_value, detected_at, sources, confidence, severity, fpl_impact, action_required) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,0)",
        (event_type, entity, entity_id, old_value, new_value, detected_at, json.dumps([source]), confidence, severity, fpl_impact),
    )


def snapshot_player_state(conn: sqlite3.Connection) -> dict[int, dict]:
    rows = conn.execute("SELECT id, team_id, status, removed FROM players").fetchall()
    return {r["id"]: {"team_id": r["team_id"], "status": r["status"], "removed": r["removed"]} for r in rows}


def snapshot_setpiece_state(conn: sqlite3.Connection) -> dict[int, tuple]:
    rows = conn.execute(
        f"SELECT player_id, {','.join(_SETPIECE_FIELDS)} FROM player_setpiece_history WHERE valid_until IS NULL"
    ).fetchall()
    return {r["player_id"]: tuple(r[f] for f in _SETPIECE_FIELDS) for r in rows}


def detect_player_lifecycle_changes(
    conn: sqlite3.Connection, prev_state: dict[int, dict], new_rows: list[dict], now: str, source: str
) -> int:
    changed = 0
    new_ids = set()

    for row in new_rows:
        pid = row["id"]
        new_ids.add(pid)
        prev = prev_state.get(pid)

        if prev is None:
            record_event(conn, "new_player", "player", pid, None, row["web_name"], now, source, "CONFIRMED", "MEDIUM")
            changed += 1
            continue

        if prev["removed"] == 0 and row["removed"] == 1:
            record_event(conn, "removed_player", "player", pid, row["web_name"], None, now, source, "CONFIRMED", "MEDIUM")
            changed += 1

        if prev["team_id"] != row["team_id"]:
            record_event(
                conn, "club_change", "player", pid, str(prev["team_id"]), str(row["team_id"]),
                now, source, "CONFIRMED", "HIGH",
            )
            changed += 1

        if prev["status"] != row["status"]:
            record_event(
                conn, "status_change", "player", pid, prev["status"], row["status"],
                now, source, "CONFIRMED", _status_severity(prev["status"], row["status"]),
            )
            changed += 1

    for pid in set(prev_state.keys()) - new_ids:
        record_event(conn, "removed_player", "player", pid, "present", "absent", now, source, "CONFIRMED", "MEDIUM")
        changed += 1

    return changed


def detect_setpiece_changes(
    conn: sqlite3.Connection, prev_state: dict[int, tuple], new_rows: list[dict], now: str, source: str
) -> int:
    changed = 0
    for r in new_rows:
        pid = r["player_id"]
        old_tuple = prev_state.get(pid)
        new_tuple = tuple(r[f] for f in _SETPIECE_FIELDS)
        if old_tuple is not None and old_tuple != new_tuple:
            record_event(
                conn, "setpiece_change", "player", pid,
                json.dumps(old_tuple), json.dumps(new_tuple),
                now, source, "CONFIRMED", _setpiece_severity(old_tuple, new_tuple),
            )
            changed += 1
    return changed
