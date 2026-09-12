"""One authoritative gameweek lifecycle state (2026-08-22, automation-lifecycle
pass) - the single real signal `run_scheduled`/`live_match_poll_cmd` (scheduler),
`optimization/post_gw_pipeline.py` (optimizer trigger), and
`monitoring/dashboard.py` (product state) all read, instead of each deriving its
own separate notion of "what stage is the gameweek in". Pure DERIVED function -
recomputed fresh from real DB state every call, no in-memory/process state, so a
process restart mid-gameweek is automatically correct (nothing to recover).

States: PRE_DEADLINE -> LOCKED -> LIVE -> GW_FINISHED-family (NEXT_GW_ANALYSIS ->
READY_FOR_NEXT_DEADLINE) -> back to PRE_DEADLINE for the next event. UNKNOWN is a
real, honest data-integrity fallback (see `_fixture_data_is_trustworthy`), never a
normal product state - a genuinely incomplete/missing/degraded fixture picture must
never be silently read as "finished" and trigger the post-GW pipeline.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from fpl_agent.models.fixtures import finished_fixture_ids_fast, live_or_reference_event

_GW_FINISHED_STATES = ("GW_FINISHED", "NEXT_GW_ANALYSIS", "READY_FOR_NEXT_DEADLINE")

# Two markers, not one - real production-correctness reason (2026-08-22): if the
# post-GW pipeline crashes partway through, "started but not done" must keep
# reading as real, in-progress work (NEXT_GW_ANALYSIS), not silently revert to
# looking freshly-untouched (GW_FINISHED) - every step inside the pipeline is
# itself idempotent (enqueue_analysis_job/log_decision/the app_meta marker
# itself), so simply re-running it is always safe and eventually reaches "done".
_STARTED_KEY = "post_gw_pipeline_started_event"
_DONE_KEY = "post_gw_pipeline_done_event"


@dataclass(frozen=True)
class GWLifecycleState:
    event: int
    state: str  # PRE_DEADLINE | LOCKED | LIVE | NEXT_GW_ANALYSIS | READY_FOR_NEXT_DEADLINE | UNKNOWN
    deadline_utc: str | None
    any_started: bool
    all_finished: bool
    data_valid: bool


def _resolve_anchor_event(conn: sqlite3.Connection) -> int | None:
    """Real bug found live 2026-09-12, ~13 minutes after a real GW4 deadline:
    FPL's own `events.is_current` stayed pinned to GW3 well past GW4's
    deadline (confirmed directly against FPL's own live bootstrap-static API,
    not just this project's synced copy - `is_current` genuinely doesn't
    flip until kickoffs start, not at the deadline). Blindly trusting
    `is_current` therefore anchored the whole lifecycle/dashboard state to a
    gameweek that had been fully finished for a week, showing a stale
    "next deadline" countdown for a deadline that had already passed - the
    same real product-visible bug `live_or_reference_event`'s own
    `current_live_event`/`_imminent_unfinished_event` helpers exist to avoid
    for other callers, just never applied here.

    Fixed by keeping `is_current` as the anchor ONLY while that gameweek
    still has a real fixture that isn't finished yet (i.e. it could
    plausibly still be "current") - once every one of its own fixtures is
    finished, defer to `live_or_reference_event` the same way every other
    real caller in this codebase already does."""
    row = conn.execute("SELECT id FROM events WHERE is_current=1 LIMIT 1").fetchone()
    fallback = live_or_reference_event(conn)
    if row is None:
        return fallback
    anchor = row["id"]
    if fallback is not None and fallback != anchor:
        unfinished = conn.execute(
            "SELECT 1 FROM fixtures WHERE event=? AND (finished=0 OR finished IS NULL) LIMIT 1", (anchor,)
        ).fetchone()
        if unfinished is None:
            return fallback
    return anchor


def _fixture_data_is_trustworthy(conn: sqlite3.Connection, event: int) -> bool:
    """Real, direct-requirement guard: never let a missing/incomplete/degraded
    fixture picture masquerade as "the gameweek is finished". All four must hold:
    (1) at least one real fixture row exists for this event - an empty set is
    never "complete" (guards the `all([]) == True` vacuous-truth trap explicitly);
    (2) every one of those rows has a real, non-NULL `finished` value - no
    partially-ingested row silently treated as resolved; (3) the fixtures source
    itself is currently healthy (`failure_count == 0`, the same DEGRADED signal
    `fpl doctor`/`readiness` already use elsewhere in this project) - a fixtures
    sync that's currently failing must never have its last-known row count
    trusted as current/complete; (4) the event's own row resolves cleanly (a real
    deadline_time present, not a malformed/placeholder row)."""
    fixtures = conn.execute(
        "SELECT finished FROM fixtures WHERE event=?", (event,)
    ).fetchall()
    if not fixtures:
        return False
    if any(f["finished"] is None for f in fixtures):
        return False

    health = conn.execute(
        "SELECT failure_count FROM source_health WHERE source_name='fpl_api_fixtures'"
    ).fetchone()
    if health is None or health["failure_count"] not in (0, None):
        return False

    event_row = conn.execute(
        "SELECT deadline_time FROM events WHERE id=?", (event,)
    ).fetchone()
    if event_row is None or not event_row["deadline_time"]:
        return False

    return True


def compute_gw_lifecycle_state(conn: sqlite3.Connection) -> GWLifecycleState | None:
    event = _resolve_anchor_event(conn)
    if event is None:
        return None

    fixtures_raw = conn.execute(
        "SELECT id, started, finished FROM fixtures WHERE event=?", (event,)
    ).fetchall()
    finished_ids = finished_fixture_ids_fast(conn, event)
    resolved_finished = [
        bool(f["finished"]) or f["id"] in finished_ids for f in fixtures_raw
    ]
    any_started = any(f["started"] for f in fixtures_raw)
    all_finished = bool(fixtures_raw) and all(resolved_finished)

    data_valid = _fixture_data_is_trustworthy(conn, event)

    event_row = conn.execute("SELECT deadline_time FROM events WHERE id=?", (event,)).fetchone()
    deadline_utc = event_row["deadline_time"] if event_row else None

    if all_finished and data_valid:
        done_row = conn.execute("SELECT value FROM app_meta WHERE key=?", (_DONE_KEY,)).fetchone()
        started_row = conn.execute("SELECT value FROM app_meta WHERE key=?", (_STARTED_KEY,)).fetchone()
        done_event = int(done_row["value"]) if done_row and done_row["value"] else None
        started_event = int(started_row["value"]) if started_row and started_row["value"] else None
        if done_event == event:
            state = "READY_FOR_NEXT_DEADLINE"
        elif started_event == event:
            state = "NEXT_GW_ANALYSIS"  # pipeline has begun (or crashed mid-way) - real in-progress signal
        else:
            state = "GW_FINISHED"  # freshly detected, pipeline hasn't started yet
    elif any_started:
        state = "LIVE"
    elif not data_valid:
        # Real, honest "can't tell" fallback - never PRE_DEADLINE (which implies
        # a normal, trusted upcoming gameweek) when the underlying fixture data
        # for this event genuinely can't be trusted yet.
        state = "UNKNOWN"
    elif deadline_utc and _deadline_passed(deadline_utc):
        state = "LOCKED"
    else:
        state = "PRE_DEADLINE"

    return GWLifecycleState(
        event=event, state=state, deadline_utc=deadline_utc,
        any_started=any_started, all_finished=all_finished, data_valid=data_valid,
    )


def _deadline_passed(deadline_utc: str) -> bool:
    try:
        deadline = datetime.fromisoformat(deadline_utc.replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.now(timezone.utc) >= deadline


def is_gw_finished_family(state: str) -> bool:
    return state in _GW_FINISHED_STATES


def needs_post_gw_pipeline(state: str) -> bool:
    """GW_FINISHED (freshly detected) or NEXT_GW_ANALYSIS (started but not
    marked done - a real crash-recovery case, safe to re-run) both mean the
    pipeline still has real work to do for this event."""
    return state in ("GW_FINISHED", "NEXT_GW_ANALYSIS")
