"""Real "is the current recommendation still current" check (2026-08-29, P0
product audit: "the dashboard must NEVER show a stale strategic decision as
current"). `strategic_plan`/`transfer_analysis` are cached decisions (the
beam search/starting-action comparison is too expensive to re-run on every
dashboard regen - see CLAUDE.md's own "Cheap dashboard refresh vs expensive
strategic recomputation" rule) - so the dashboard's job is not to fake
liveness, it's to disclose staleness honestly.

`assess_recommendation_freshness` answers one narrow question: has any
already-recorded, genuinely material change (`change_events`, the project's
own real change-detection log - price/status/club/lineup changes, HIGH
severity only) happened to a squad-relevant player SINCE this decision was
computed? A HIGH-severity `change_events` row is already the project's own
bar for "significant enough to escalate" (see `ingestion/change_detection.py`
- injury/suspension, club change, a squad player's price move, a lineup
status crossing the squad-selection gate) - reusing that existing severity
taxonomy rather than inventing a second one."""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class FreshnessResult:
    computed_at: str | None
    decision_id: int | None
    model_version: str | None
    age_relative: str  # human label, e.g. "3h ago" - reuses dashboard._relative_time
    is_stale: bool
    stale_reason: str | None  # e.g. "Haaland: status_change (a -> i) detected 2026-08-29T10:03Z"
    # Real timestamp of the triggering change_events row itself (2026-08-28,
    # direct user requirement: "Stale · new lineup information detected 34s
    # ago" - the STALE label's own age must be how long ago the material
    # change was detected, never the OLD decision's own `computed_at` age,
    # which would make a genuinely-just-detected change read as if it were
    # hours stale). `None` whenever `is_stale` is False - nothing to date.
    stale_detected_at: str | None = None


def has_material_change_since(
    conn: sqlite3.Connection, since_iso: str, squad_ids: set[int] | None = None,
) -> dict | None:
    """Real query, not a heuristic: the most recent HIGH-severity
    `change_events` row detected strictly after `since_iso`, scoped to
    squad players when `squad_ids` is given (a change to a player nobody
    owns doesn't make an existing recommendation stale) plus any
    non-player-entity HIGH event (kept unscoped - e.g. a fixture-level
    change) since those aren't squad-attributable the same way. Returns
    the raw row as a dict, or None when nothing material happened."""
    squad_ids = squad_ids or set()
    if squad_ids:
        placeholders = ",".join("?" * len(squad_ids))
        row = conn.execute(
            f"""
            SELECT event_type, entity, entity_id, old_value, new_value, detected_at
            FROM change_events
            WHERE severity='HIGH' AND detected_at > ?
              AND (entity != 'player' OR entity_id IN ({placeholders}))
            ORDER BY detected_at DESC LIMIT 1
            """,
            (since_iso, *squad_ids),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT event_type, entity, entity_id, old_value, new_value, detected_at "
            "FROM change_events WHERE severity='HIGH' AND detected_at > ? "
            "ORDER BY detected_at DESC LIMIT 1",
            (since_iso,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def _player_name(conn: sqlite3.Connection, player_id: int) -> str:
    row = conn.execute("SELECT web_name FROM players WHERE id=?", (player_id,)).fetchone()
    return row["web_name"] if row is not None else f"player {player_id}"


def assess_recommendation_freshness(
    conn: sqlite3.Connection, strategic_decision, squad_ids: set[int] | None,
) -> FreshnessResult | None:
    """`strategic_decision` is the raw `Decision` row (`database.decisions.Decision`)
    the dashboard's `current_rec`/`sd` were read from this regen - `None` when no
    `strategic_plan` has ever been logged (a separate, already-handled empty
    state, not "stale"). Never re-runs the beam search itself - purely reads
    `created_at` plus the already-recorded change log."""
    from fpl_agent.monitoring.dashboard.legacy import _relative_time

    if strategic_decision is None:
        return None
    change = has_material_change_since(conn, strategic_decision.created_at, squad_ids)
    stale_reason = None
    if change is not None:
        if change["entity"] == "player":
            name = _player_name(conn, change["entity_id"])
            stale_reason = f"{name}: {change['event_type']} ({change['old_value']} -> {change['new_value']})"
        else:
            stale_reason = f"{change['entity']} {change['entity_id']}: {change['event_type']}"
    return FreshnessResult(
        computed_at=strategic_decision.created_at,
        decision_id=strategic_decision.id,
        model_version=strategic_decision.model_version,
        age_relative=_relative_time(strategic_decision.created_at),
        is_stale=change is not None,
        stale_reason=stale_reason,
        stale_detected_at=change["detected_at"] if change is not None else None,
    )
