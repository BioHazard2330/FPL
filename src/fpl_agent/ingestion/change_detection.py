import json
import sqlite3
from datetime import datetime, timedelta, timezone

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


# --- Live-gameweek layer (2026-08-21): price / predicted-lineup / kickoff
# change detection, real push-notification events, not just current-state
# storage. All three are scoped to a real tracked squad
# (ingestion/my_team.py::resolve_tracked_squad_ids) wherever that scoping
# is meaningful - see that function's own docstring for why: this project's
# Tier 2-4 sources cover ~380-390 players, and alerting on every one of
# their fluctuations would be exactly the "obnoxious" outcome explicitly
# ruled out for this feature. Price changes are the one exception (every
# squad's OWN market value matters regardless of squad membership, and the
# real event is genuinely rare - a handful of players a day, not hundreds)
# - scoped instead by ESCALATING severity for a tracked-squad player rather
# than filtering non-squad ones out entirely, so `fpl changes`/the dashboard
# still show the full real picture; only the escalated (HIGH) ones clear
# the existing alert bar (severity 85's own "HIGH/CRITICAL only" rule,
# unchanged) and reach a push notification. ------------------------------


def snapshot_price_state(conn: sqlite3.Connection) -> dict[int, int]:
    rows = conn.execute(
        "SELECT player_id, value_tenths FROM player_price_history WHERE valid_until IS NULL"
    ).fetchall()
    return {r["player_id"]: r["value_tenths"] for r in rows}


def detect_price_changes(
    conn: sqlite3.Connection, prev_state: dict[int, int], new_rows: list[dict], now: str, source: str,
    tracked_squad_ids: set[int] | None = None,
) -> int:
    """`new_rows` is the same normalize_player_prices(bootstrap) list
    sync_price_history already consumes - `prev_state` must be snapshotted
    (snapshot_price_state) BEFORE that sync call runs, same before/after
    shape as detect_player_lifecycle_changes above. A player absent from
    prev_state (first time this project has ever seen their price) is never
    reported as a "change" - there's nothing real to compare against."""
    tracked_squad_ids = tracked_squad_ids or set()
    changed = 0
    for row in new_rows:
        pid = row["player_id"]
        new_value = row["value_tenths"]
        old_value = prev_state.get(pid)
        if old_value is None or old_value == new_value:
            continue
        direction = "rise" if new_value > old_value else "fall"
        severity = "HIGH" if pid in tracked_squad_ids else "MEDIUM"
        record_event(
            conn, "price_change", "player", pid,
            f"{old_value / 10:.1f}", f"{new_value / 10:.1f}",
            now, source, "CONFIRMED", severity, fpl_impact=direction,
        )
        changed += 1
    return changed


# Must match optimization/squad.py::_MIN_START_PERCENT_FOR_SQUAD - kept as
# its own local constant rather than imported, since ingestion/ modules
# don't import from optimization/ (the reverse already happens:
# optimization/squad.py imports ingestion/lineup_probability_source.py -
# importing back the other way would be a real layering cycle risk for a
# single shared number).
_SQUAD_SELECTION_START_PERCENT_GATE = 70
_START_PERCENT_CHANGE_THRESHOLD = 20  # a real, meaningfully large swing - not every 1-point wobble


def detect_predicted_lineup_status_changes(
    conn: sqlite3.Connection, prev_state: dict[int, str], tracked_squad_ids: set[int], now: str, source: str,
) -> int:
    """`prev_state` ({player_id: predicted_status}) must be snapshotted
    BEFORE a fresh sync_predicted_lineups() call, which deletes+re-inserts
    the whole current-state table (migration 0019's own docstring: "a stale
    predicted XI has no standing value once a fresher one exists") - that
    delete+insert is exactly why "what changed" can only be answered by
    snapshotting first, there is no history table underneath to diff
    against. Scoped to `tracked_squad_ids` only (see this module's own
    top-of-section note) - a player entirely new to this source (no prior
    observation) is never reported as a "change". A tracked player who
    HAD a row before and now has none at all (the source stopped covering
    them) is treated as new_status=None, same as any other real status
    change - a squad player silently dropping out of coverage is exactly
    the kind of gap this feature exists to surface, not hide."""
    if not tracked_squad_ids:
        return 0
    changed = 0
    placeholders = ",".join("?" * len(tracked_squad_ids))
    rows = conn.execute(
        f"SELECT player_id, predicted_status FROM predicted_lineup_players WHERE player_id IN ({placeholders})",
        tuple(tracked_squad_ids),
    ).fetchall()
    new_state = {r["player_id"]: r["predicted_status"] for r in rows}
    for pid in tracked_squad_ids:
        old_status = prev_state.get(pid)
        new_status = new_state.get(pid)
        if old_status is None or old_status == new_status:
            continue
        severity = "HIGH" if old_status == "starting" and new_status != "starting" else "MEDIUM"
        record_event(
            conn, "predicted_lineup_change", "player", pid, old_status, new_status,
            now, source, "strong_reporter", severity,
        )
        changed += 1
    return changed


def snapshot_start_percent_state(conn: sqlite3.Connection, tracked_squad_ids: set[int]) -> dict[int, int]:
    if not tracked_squad_ids:
        return {}
    placeholders = ",".join("?" * len(tracked_squad_ids))
    rows = conn.execute(
        f"SELECT player_id, start_percent FROM player_start_probability WHERE player_id IN ({placeholders})",
        tuple(tracked_squad_ids),
    ).fetchall()
    return {r["player_id"]: r["start_percent"] for r in rows}


def detect_start_percent_changes(
    conn: sqlite3.Connection, prev_state: dict[int, int], tracked_squad_ids: set[int], now: str, source: str,
) -> int:
    """Same before/after snapshot requirement as detect_predicted_lineup_status_changes
    (player_start_probability is also delete+insert current-state, migration
    0021). Only fires on a real, meaningfully large swing
    (_START_PERCENT_CHANGE_THRESHOLD), not every single-point wobble - and
    escalates to HIGH specifically when the swing crosses this project's own
    real squad-selection gate (_SQUAD_SELECTION_START_PERCENT_GATE) in
    either direction, since that's the one move genuinely actionable enough
    to justify a push notification (a squad member's real inclusion
    rationale just changed), not merely "this number moved a bit"."""
    if not tracked_squad_ids:
        return 0
    changed = 0
    new_state = snapshot_start_percent_state(conn, tracked_squad_ids)
    for pid in tracked_squad_ids:
        old_pct = prev_state.get(pid)
        new_pct = new_state.get(pid)
        if old_pct is None or new_pct is None or old_pct == new_pct:
            continue
        if abs(new_pct - old_pct) < _START_PERCENT_CHANGE_THRESHOLD:
            continue
        gate = _SQUAD_SELECTION_START_PERCENT_GATE
        crossed_gate = (old_pct >= gate > new_pct) or (old_pct < gate <= new_pct)
        severity = "HIGH" if crossed_gate else "MEDIUM"
        record_event(
            conn, "start_percent_change", "player", pid, str(old_pct), str(new_pct),
            now, source, "strong_reporter", severity,
        )
        changed += 1
    return changed


_KICKOFF_REMINDER_WINDOW_MINUTES = 90  # comfortably wider than the Windows
# Task Scheduler's default fixed 60min interval (scripts/setup_scheduler.ps1)
# - the scheduler is NOT adaptive (Phase 7's own disclosed limitation: "OS
# scheduler triggers a fixed interval, it doesn't dynamically re-schedule
# itself"), so this window has to be wide enough that at least one real poll
# is guaranteed to land inside it before kickoff even in the worst case (a
# poll landing exactly as the window opens, the next one a full interval
# later). Real, disclosed dependency: this only fires reliably if the
# scheduler is actually registered (`fpl scheduler-status`) - the user's own
# still-pending choice per Phase 7, unchanged by this feature.


def detect_upcoming_kickoffs(
    conn: sqlite3.Connection, tracked_squad_ids: set[int], now_dt: datetime,
    window_minutes: int = _KICKOFF_REMINDER_WINDOW_MINUTES,
) -> int:
    """Fires at most once per real fixture (idempotency guard: a
    change_events row already existing for this exact
    event_type/entity/entity_id means "already reminded", checked before
    inserting another) - never a repeat reminder on the next poll cycle just
    because the fixture is still upcoming. Tier 1 CONFIRMED data
    (fixtures.kickoff_time, straight from the official FPL API, not a
    Tier 2-4 source) - always HIGH severity, matching this project's own
    precedent that a genuinely time-critical, narrowly-scoped event (see
    live_bonus.py's real match events) doesn't need severity nuance the way
    a status change does."""
    if not tracked_squad_ids:
        return 0
    team_placeholders = ",".join("?" * len(tracked_squad_ids))
    team_rows = conn.execute(
        f"SELECT DISTINCT team_id FROM players WHERE id IN ({team_placeholders}) AND team_id IS NOT NULL",
        tuple(tracked_squad_ids),
    ).fetchall()
    team_ids = [r["team_id"] for r in team_rows]
    if not team_ids:
        return 0

    window_end = now_dt + timedelta(minutes=window_minutes)
    team_ph = ",".join("?" * len(team_ids))
    fixtures = conn.execute(
        f"SELECT id, kickoff_time FROM fixtures WHERE started=0 AND kickoff_time IS NOT NULL "
        f"AND (team_h IN ({team_ph}) OR team_a IN ({team_ph}))",
        tuple(team_ids) * 2,
    ).fetchall()

    fired = 0
    for f in fixtures:
        raw = f["kickoff_time"]
        try:
            kickoff_dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if not (now_dt <= kickoff_dt <= window_end):
            continue
        already = conn.execute(
            "SELECT 1 FROM change_events WHERE event_type='kickoff_reminder' AND entity='fixture' AND entity_id=?",
            (f["id"],),
        ).fetchone()
        if already is not None:
            continue
        record_event(
            conn, "kickoff_reminder", "fixture", f["id"], None, raw,
            now_dt.isoformat(), "fpl_api_fixtures", "CONFIRMED", "HIGH",
        )
        fired += 1
    return fired
