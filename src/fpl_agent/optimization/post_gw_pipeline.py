"""The deterministic, no-LLM post-gameweek pipeline (2026-08-22, automation-
lifecycle pass, item 5). Runs once a gameweek's real lifecycle state reaches
`GW_FINISHED`/`NEXT_GW_ANALYSIS` (`models.gw_lifecycle.needs_post_gw_pipeline`) -
never calls an LLM, never touches the qualitative-analysis jobs themselves
(that stays a real Claude Code skill invocation, drained whenever the user next
opens a session - see `.claude/hooks/queue_check.py`). Everything here reuses
already-tested machinery: `optimization.decision_engine.evaluate_locked_squad`
for captain/transfer, `optimization.chips` for the chip verdict. This is the ONE
place a full wildcard/free-hit ILP re-solve is affordable - it runs once per
gameweek via the idempotency marker below, not on every dashboard regen."""

import sqlite3
from dataclasses import dataclass

from fpl_agent.database.decisions import log_decision
from fpl_agent.ingestion.analysis_queue import enqueue_analysis_job
from fpl_agent.ingestion.fotmob_source import refresh_in_progress_matches
from fpl_agent.models.calibration import record_outcomes_for_finished_event
from fpl_agent.models.gw_lifecycle import compute_gw_lifecycle_state, needs_post_gw_pipeline
from fpl_agent.optimization.chips import (
    bench_boost_value,
    eligible_chips,
    freehit_value,
    triple_captain_value,
    wildcard_value,
)
from fpl_agent.optimization.decision_engine import evaluate_locked_squad
from fpl_agent.optimization.locked_squad import get_locked_squad


@dataclass(frozen=True)
class PostGwPipelineResult:
    ran: bool
    event: int | None
    reason: str
    decision_id: int | None = None


def _backfill_missing_analysis_jobs(conn: sqlite3.Connection) -> int:
    """Defensive, permanent version of the manual backfill this project did
    by hand once (2026-08-22, earlier the same day) for Arsenal-Coventry -
    any real FULL_TIME match that somehow never got a job queued (a genuine
    gap the same day's own earlier fix closed for the normal transition
    path, but this catches any other way it could happen) gets one now,
    idempotent (`enqueue_analysis_job`), never fabricates analysis itself."""
    rows = conn.execute(
        "SELECT mi.id AS match_id, ht.short_name AS home, at.short_name AS away, "
        "mi.home_score, mi.away_score "
        "FROM match_intelligence mi "
        "JOIN teams ht ON ht.id = mi.home_team_id JOIN teams at ON at.id = mi.away_team_id "
        "WHERE mi.status='FULL_TIME'"
    ).fetchall()
    backfilled = 0
    for r in rows:
        evidence = f"{r['home']} {r['home_score']}-{r['away_score']} {r['away']} (final)"
        if enqueue_analysis_job(conn, r["match_id"], "FULL_TIME", evidence):
            backfilled += 1
    return backfilled


def run_post_gw_pipeline(conn: sqlite3.Connection, event: int) -> PostGwPipelineResult:
    """The actual deterministic sequence - see module docstring for what it
    does and doesn't do. Marks itself started/done via `app_meta` so a crash
    partway through leaves the real lifecycle state honestly at
    NEXT_GW_ANALYSIS (in-progress) rather than silently reverting to
    GW_FINISHED - every step below is itself idempotent, so simply calling
    this again is always safe."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('post_gw_pipeline_started_event', ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (str(event), now),
    )
    conn.commit()

    # 1. Real finalization pass - belt-and-suspenders, matches match state one
    #    more time (cheap: only re-syncs rows that aren't already FULL_TIME).
    refresh_in_progress_matches(conn)

    # 2. Backfill any FULL_TIME match still missing a queued analysis job.
    _backfill_missing_analysis_jobs(conn)

    # 3. Real locked squad - never fabricate a plan against nothing.
    locked = get_locked_squad(conn)
    if locked is None:
        return PostGwPipelineResult(ran=False, event=event, reason="no locked squad to plan against")

    # 4. Captain + transfer verdicts (existing, cheap, already-tested).
    decision = evaluate_locked_squad(conn, locked)

    # 5. Chip verdict - the one place a full wildcard/free-hit re-solve is
    #    affordable (once per gameweek, not every dashboard regen).
    squad_list = sorted(locked.squad_ids)

    # 5b. Real outcome capture for calibration/learning (section R) - the
    # gameweek has genuinely finished at this point (that's what triggered
    # this pipeline run), so player_stats_snapshot's event_points/minutes
    # still correctly reflect it (they get overwritten once the NEXT
    # gameweek starts generating points) - this is the real, time-sensitive
    # moment to capture it, not something safely deferrable.
    record_outcomes_for_finished_event(conn, event, squad_list)

    windows = eligible_chips(conn, event)
    bb = bench_boost_value(conn, squad_list)
    tc = triple_captain_value(conn, squad_list)
    wc = wildcard_value(conn, squad_list, n_gw=5)
    fh = freehit_value(conn, squad_list)

    summary = (
        f"captain={decision.captain_action.kind} transfer={decision.transfer_action.kind} "
        f"bboost={bb} tc={tc} wildcard={wc} freehit={fh}"
    )
    detail = {
        "event": event,
        "captain": {
            "kind": decision.captain_action.kind,
            "current": decision.captain_action.current.web_name if decision.captain_action.current else None,
            "suggested": decision.captain_action.suggested.web_name if decision.captain_action.suggested else None,
            "delta": decision.captain_action.delta,
        },
        "transfer": {
            "kind": decision.transfer_action.kind,
            "delta": decision.transfer_action.delta,
        },
        "risks": decision.risks,
        "bench_boost": bb, "triple_captain": tc, "wildcard_5gw": wc, "free_hit": fh,
        "eligible_chip_windows": [w.name for w in windows if w.eligible_now],
    }
    decision_id = log_decision(conn, "post_gw_plan", summary, detail, confidence="low")
    # Same detail shape the existing `fpl chips`/Chip Strategy panel already
    # reads via latest_decision_of_type(conn, "chip") - logging here too so
    # that panel's "as of Xh ago" refreshes automatically post-GW.
    log_decision(
        conn, "chip", summary=f"bboost={bb} tc={tc} wildcard={wc} freehit={fh}",
        detail={"bench_boost": bb, "triple_captain": tc, "wildcard_5gw": wc, "free_hit": fh},
    )

    conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('post_gw_pipeline_done_event', ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (str(event), now),
    )
    conn.commit()

    return PostGwPipelineResult(ran=True, event=event, reason="completed", decision_id=decision_id)


def _has_material_change_since_last_plan(conn: sqlite3.Connection) -> bool:
    """Real gap found 2026-08-26 (section I of a GW1-postmortem ask): once
    `run_post_gw_pipeline` has run once for a gameweek, it never runs again
    while the lifecycle sits in READY_FOR_NEXT_DEADLINE - so the persisted
    `post_gw_plan`/`chip` decisions (the dashboard's Next GW Plan / Chip
    Strategy panels) go stale the moment a real, squad-relevant event
    happens afterward (an injury, a confirmed-benched lineup, an escalated
    price move). Deliberately narrow, matching "do NOT run a full strategic
    optimization for every irrelevant event": only a real HIGH/CRITICAL
    `change_events` row (the same severity bar `fpl alerts` already uses)
    on a player actually IN the locked squad, detected after the last real
    pipeline run, counts as material. Live captain/transfer verdicts are
    already continuously recomputed on every dashboard regen
    (`evaluate_locked_squad`) regardless of this check - what this closes is
    the CHIP verdict and the persisted plan snapshot, which are only ever
    computed inside the (otherwise one-shot) pipeline."""
    locked = get_locked_squad(conn)
    if locked is None or not locked.squad_ids:
        return False
    last_run = conn.execute(
        "SELECT updated_at FROM app_meta WHERE key='post_gw_pipeline_done_event'"
    ).fetchone()
    if last_run is None:
        return False
    squad_ids = sorted(locked.squad_ids)
    placeholders = ",".join("?" * len(squad_ids))
    hit = conn.execute(
        f"SELECT 1 FROM change_events WHERE entity='player' AND entity_id IN ({placeholders}) "
        f"AND severity IN ('HIGH','CRITICAL') AND detected_at > ? LIMIT 1",
        [*squad_ids, last_run["updated_at"]],
    ).fetchone()
    return hit is not None


def maybe_run_post_gw_pipeline(conn: sqlite3.Connection) -> PostGwPipelineResult | None:
    """The real entry point wired into the daemon (`run_scheduled`/
    `live_match_poll_cmd`) - a pure, cheap no-op unless the real lifecycle
    state (`models.gw_lifecycle`) says there's genuine post-GW work left, OR
    (once already READY_FOR_NEXT_DEADLINE) a real material squad-relevant
    change has happened since the last run - see
    `_has_material_change_since_last_plan`'s own docstring."""
    lifecycle = compute_gw_lifecycle_state(conn)
    if lifecycle is None:
        return None
    if needs_post_gw_pipeline(lifecycle.state):
        return run_post_gw_pipeline(conn, lifecycle.event)
    if lifecycle.state == "READY_FOR_NEXT_DEADLINE" and _has_material_change_since_last_plan(conn):
        return run_post_gw_pipeline(conn, lifecycle.event)
    return None
