"""Closes the standing "adaptive re-scheduling would need the scheduler to
re-register itself, not built this phase" gap (Phase 7 docstring in
scheduler/cadence.py). Windows Task Scheduler triggers on a fixed interval
it was registered with - `recommended_cadence()` already computes the real,
freshness.yaml-sourced interval that SHOULD be running (15/30/60/360min
depending on hours-to-deadline), but nothing ever compared the two and
re-registered when they drifted apart. Direct user ask (2026-08-20, <24h
before the GW1 deadline): "must be active always... if something happens,
instant update" - the honest, non-fabricated way to get as close to that as
a free, local, no-paid-infra architecture supports is to make the poll
interval genuinely track the real deadline-proximity thresholds already
defined in config/freshness.yaml, automatically, every cycle - not a new
arbitrary "instant" number.

The currently-registered interval is persisted in app_meta (same pattern as
sync.py::sync_total_players) rather than parsed back out of Task
Scheduler's own XML/ISO8601 duration format - simpler and avoids a fragile
PowerShell round-trip just to read back what this project itself set."""
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

from fpl_agent.config import PROJECT_ROOT
from fpl_agent.scheduler.cadence import recommended_cadence
from fpl_agent.scheduler.status import check_scheduler_registered

_SETUP_SCRIPT = PROJECT_ROOT / "scripts" / "setup_scheduler.ps1"


def _current_registered_interval(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT value FROM app_meta WHERE key='scheduler_interval_minutes'").fetchone()
    return int(row["value"]) if row else None


def _persist_registered_interval(conn: sqlite3.Connection, minutes: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('scheduler_interval_minutes', ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (str(minutes), now),
    )
    conn.commit()


def maybe_retighten_scheduler(conn: sqlite3.Connection) -> str | None:
    """Call once per `fpl run-scheduled` cycle. Returns a human-readable
    message if the scheduler's interval was just changed, None otherwise
    (including: not Windows, not registered, or already at the right
    cadence - all real no-ops, never an error). Never raises - a failed
    re-registration attempt must not take down the sync it's piggybacking
    on, same non-fatal posture as the dashboard regeneration call site."""
    if sys.platform != "win32":
        return None
    if check_scheduler_registered() is None:
        return None  # not registered - nothing to adapt (user's own standing choice)

    cadence = recommended_cadence(conn)
    current = _current_registered_interval(conn)
    if current == cadence.interval_minutes:
        return None

    try:
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(_SETUP_SCRIPT),
             "-IntervalMinutes", str(cadence.interval_minutes)],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None

    _persist_registered_interval(conn, cadence.interval_minutes)
    return f"scheduler retightened {current}->{cadence.interval_minutes}min ({cadence.reason})"
