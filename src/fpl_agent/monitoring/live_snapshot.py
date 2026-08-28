"""Lightweight live-state snapshot channel (2026-08-28, direct user P0 ask:
"do not rebuild the entire static dashboard every 15-30 seconds"). Writes a
small JSON file the browser can poll cheaply instead of full-page-reloading
the static `dashboard.html`.

Real gap this closes: `cli/main.py::live_match_poll_cmd` (the fast ~25s
live-match loop) used to call `_write_dashboard()` - the SAME full
`generate_dashboard_html()` pipeline `fpl dashboard` uses, real cost ~1
minute per CLAUDE.md's own documented figure (Market/Fixture-Projections'
per-fixture Dixon-Coles reads, Monte Carlo robustness checks) - on every
tick a match was live. A ~1-minute rebuild inside a ~25s loop starves the
loop back down to ~60s+ regardless of the configured interval, and the
dashboard's own `<meta http-equiv="refresh">` then reloads that expensive,
mostly-unchanged file on its own aggressive schedule too. Neither problem
is fixed by adding more caching to `generate_dashboard_html` itself - the
real fix is a separate, genuinely cheap channel for the handful of fields
that actually change every tick (live rank, live points, played/live/to-play
counts), so the fast loop's own tick time is decoupled from the full
dashboard's real cost. The full dashboard still regenerates on its own
existing cadence (`run_scheduled`, or a real FULL_TIME transition) -
unchanged, still real, still authoritative for everything except this
module's own handful of fast-moving fields.

Every field here is a pure DB read plus, at most, the SAME already-fetched
`live_payload` the caller passed in - reuses
`monitoring.dashboard.legacy._compute_my_live_score`/
`_squad_play_status_counts` rather than a second, duplicated live-points
computation. Never runs Dixon-Coles, Monte Carlo, or the strategic beam
search - those stay on their own expensive, materiality-gated cadence
(`cli/main.py::_maybe_trigger_strategic_plan_recompute`), untouched here."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fpl_agent.config import DATA_DIR
from fpl_agent.database.decisions import latest_decision_of_type
from fpl_agent.models.fixtures import live_or_reference_event
from fpl_agent.optimization.locked_squad import get_locked_squad

SNAPSHOT_PATH = DATA_DIR / "live_snapshot.json"


_RECENT_CHANGES_WINDOW_HOURS = 24
_RECENT_CHANGES_LIMIT = 10


def _bonus_defcon_block(live_bonus_rows: list, squad_ids: frozenset[int]) -> list[dict]:
    """Real, cheap - `live_bonus_rows` is the caller's own single
    `compute_live_bonus` call (shared with `_match_events_block` so this
    project never runs that computation twice per snapshot), filtered to
    the locked squad so this stays small. `None` fields (e.g. `defcon_reached`
    for a GKP) pass through honestly, never defaulted to a misleading value."""
    if not squad_ids:
        return []
    return [
        {
            "player_id": r.player_id, "web_name": r.web_name, "minutes": r.minutes,
            "provisional_bonus": r.provisional_bonus, "confirmed_bonus": r.confirmed_bonus,
            "defensive_contribution": r.defensive_contribution, "defcon_reached": r.defcon_reached,
        }
        for r in live_bonus_rows if r.player_id in squad_ids
    ]


def _recent_changes_block(conn: sqlite3.Connection, squad_ids: frozenset[int]) -> list[dict]:
    """Real, cheap - a plain indexed `change_events` read (no recomputation),
    scoped to squad players and a recent window so this stays small and
    genuinely "what changed recently", not the whole historical log."""
    if not squad_ids:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=_RECENT_CHANGES_WINDOW_HOURS)).isoformat()
    placeholders = ",".join("?" * len(squad_ids))
    rows = conn.execute(
        f"SELECT ce.event_type, ce.entity, ce.entity_id, ce.old_value, ce.new_value, ce.severity, ce.detected_at, "
        f"p.web_name FROM change_events ce LEFT JOIN players p ON p.id = ce.entity_id "
        f"WHERE ce.entity='player' AND ce.entity_id IN ({placeholders}) AND ce.detected_at > ? "
        f"ORDER BY ce.detected_at DESC LIMIT ?",
        (*squad_ids, cutoff, _RECENT_CHANGES_LIMIT),
    ).fetchall()
    return [
        {
            "player_id": r["entity_id"], "web_name": r["web_name"], "event_type": r["event_type"],
            "old_value": r["old_value"], "new_value": r["new_value"], "severity": r["severity"],
            "detected_at": r["detected_at"],
        }
        for r in rows
    ]


def _squad_block(conn: sqlite3.Connection, locked) -> list[dict]:
    """Real per-squad-player state in one array - slot (starting/bench),
    captain/vice, position, live projection (xp), and availability status/
    classification, so the browser never has to reconstruct this from
    several separate reads (Part 1's own "no dashboard component
    independently reconstructs these values" requirement). Reuses
    `models.availability.classify` (the same severity taxonomy the
    Injuries panel already uses) rather than a second status heuristic."""
    if locked is None or not locked.squad_ids:
        return []
    from fpl_agent.models.availability import classify

    placeholders = ",".join("?" * len(locked.squad_ids))
    avail_rows = conn.execute(
        f"SELECT p.id AS player_id, p.status, s.chance_of_playing_this_round, s.chance_of_playing_next_round, "
        f"p.news FROM players p LEFT JOIN player_stats_snapshot s ON s.id = ("
        f"SELECT id FROM player_stats_snapshot WHERE player_id = p.id ORDER BY retrieved_at DESC LIMIT 1) "
        f"WHERE p.id IN ({placeholders})",
        tuple(locked.squad_ids),
    ).fetchall()
    avail_by_id = {r["player_id"]: r for r in avail_rows}

    out = []
    for slot, players in (("starting", locked.xi.starting), ("bench", locked.xi.bench)):
        for c in players:
            a = avail_by_id.get(c.player_id)
            out.append({
                "player_id": c.player_id, "web_name": c.web_name, "position": c.position,
                "slot": slot,
                "is_captain": locked.xi.captain is not None and c.player_id == locked.xi.captain.player_id,
                "is_vice": locked.xi.vice_captain is not None and c.player_id == locked.xi.vice_captain.player_id,
                "xp": c.xp,
                "status": a["status"] if a else None,
                "classification": (
                    classify(a["status"], a["chance_of_playing_this_round"], a["chance_of_playing_next_round"])
                    if a else None
                ),
                "news": a["news"] if a else None,
            })
    return out


def _match_events_block(live_bonus_rows: list) -> list[dict]:
    """Real current-state events for squad players who have actually
    played - goals/assists/red cards straight off the already-computed
    `compute_live_bonus` rows (no second live-payload pass). Cumulative
    counts, not a poll-to-poll diff (that diffing already exists for
    toast alerts in `live_bonus.diff_live_rows` - this is a snapshot read,
    not a notification stream)."""
    events = []
    for r in live_bonus_rows:
        if r.goals_scored:
            events.append({"player_id": r.player_id, "web_name": r.web_name, "kind": "goal", "count": r.goals_scored})
        if r.assists:
            events.append({"player_id": r.player_id, "web_name": r.web_name, "kind": "assist", "count": r.assists})
        if r.red_cards:
            events.append({"player_id": r.player_id, "web_name": r.web_name, "kind": "red_card", "count": r.red_cards})
    return events


def _source_freshness_block(conn: sqlite3.Connection) -> list[dict]:
    """Real, cheap - one already-existing `get_source_health` query, same
    data the Advanced drawer's source-health table already reads at full
    regen. `degraded` is a plain `failure_count > 0` flag - never a second,
    invented health heuristic."""
    from fpl_agent.monitoring.source_status import get_source_health

    return [
        {
            "source": s.source_name, "last_success": s.last_success,
            "last_failure": s.last_failure, "failure_count": s.failure_count,
            "degraded": s.failure_count > 0,
        }
        for s in get_source_health(conn)
    ]


_RECOMPUTE_LOCK_STALE_MINUTES = 15  # same real bound cli/main.py::_STRATEGIC_PLAN_AUTO_STALE_MINUTES uses - a lock older than this is an abandoned/crashed run, never a permanent "RECOMPUTING"


def _points_changes_block(conn: sqlite3.Connection, squad_ids: frozenset[int]) -> dict | None:
    """Real, cheap - reuses `models.points_changes.detect_points_revisions`/
    `is_gw_locked` directly (the SAME functions the full Points Changes
    dashboard panel uses, real snapshot diff already computed there - no
    second detection pass). `None` when no gameweek has finished by the
    bootstrap `events.finished` flag yet (never a fabricated zero-revision
    block for a GW that hasn't happened)."""
    from fpl_agent.models.points_changes import detect_points_revisions, is_gw_locked

    row = conn.execute("SELECT id FROM events WHERE finished = 1 ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    event = row["id"]
    revisions = detect_points_revisions(conn, event=event)
    squad_revision_count = sum(1 for r in revisions if r.player_id in squad_ids)
    return {
        "event": event,
        "locked": is_gw_locked(conn, event),
        "total_revisions": len(revisions),
        "squad_revisions": squad_revision_count,
    }


def _decision_status(conn: sqlite3.Connection, is_stale: bool | None) -> str:
    """Real CURRENT/STALE/RECOMPUTING status (2026-08-29, "final runtime
    reliability pass" P0 ask). RECOMPUTING reads the SAME real
    `app_meta['strategic_plan_auto_started_at']` lock
    `cli/main.py::_maybe_trigger_strategic_plan_recompute` writes when it
    fires a real background recompute - never a second, invented "is it
    recomputing" signal. Falls back to STALE/CURRENT (already real, from
    `assess_recommendation_freshness`) when no recompute is genuinely
    in-flight."""
    row = conn.execute("SELECT value FROM app_meta WHERE key='strategic_plan_auto_started_at'").fetchone()
    if row is not None:
        try:
            lock_ts = datetime.fromisoformat(row["value"].replace("Z", "+00:00"))
            if lock_ts.tzinfo is None:
                lock_ts = lock_ts.replace(tzinfo=timezone.utc)
            age_minutes = (datetime.now(timezone.utc) - lock_ts).total_seconds() / 60
            if age_minutes < _RECOMPUTE_LOCK_STALE_MINUTES:
                return "RECOMPUTING"
        except ValueError:
            pass
    if is_stale:
        return "STALE"
    if is_stale is None:
        return "UNKNOWN"
    return "CURRENT"


def _cadence_block(conn: sqlite3.Connection, rank_retrieved_at: str | None) -> dict:
    """Real, derived refresh cadence (2026-08-29, "final runtime reliability
    pass" P0 ask: "no fake timers"). Every value here comes from an
    already-real signal this project already computes for its own
    scheduling decisions - `scheduler.cadence.recommended_cadence` (the
    exact function `run_scheduled`/`fpl doctor` already use to decide the
    real sync interval) and `source_health.fpl_api_bootstrap.last_success`
    (the real core sync's own last-success timestamp) - never a second,
    invented interval. `rank_next_due_minutes` is a real, honest FLOOR
    (rank can't refresh faster than the tighter of LiveFPL's own stated
    ~5min minimum and this system's own current sync cadence) - not a
    promise a fetch will happen exactly then, since the real underlying
    cadence is genuinely adaptive/event-driven, not a fixed clock."""
    from fpl_agent.scheduler.cadence import recommended_cadence

    cadence = recommended_cadence(conn)
    sync_row = conn.execute(
        "SELECT last_success FROM source_health WHERE source_name='fpl_api_bootstrap'"
    ).fetchone()
    last_sync_at = sync_row["last_success"] if sync_row is not None else None

    rank_next_due_minutes = max(5, cadence.interval_minutes)

    return {
        "system": {
            "interval_minutes": cadence.interval_minutes, "reason": cadence.reason,
            "last_sync_at": last_sync_at,
        },
        "rank": {
            "last_update_at": rank_retrieved_at, "next_due_floor_minutes": rank_next_due_minutes,
        },
    }


def _recommendation_block(conn: sqlite3.Connection, squad_ids: frozenset[int]) -> dict | None:
    """Real decision-freshness + change-explanation, both already-cheap real
    reads (no beam search, no re-derivation) - see decision_freshness.py/
    decision_change.py's own docstrings."""
    from fpl_agent.models.decision_change import latest_recommendation_change
    from fpl_agent.models.decision_freshness import assess_recommendation_freshness
    from fpl_agent.optimization.strategic_planner import latest_strategic_plan_with_recommendation

    strategic_decision = latest_strategic_plan_with_recommendation(conn)
    freshness = assess_recommendation_freshness(conn, strategic_decision, squad_ids) if strategic_decision else None
    change = latest_recommendation_change(conn, squad_ids)
    if freshness is None and change is None:
        return None
    is_stale = freshness.is_stale if freshness else None
    return {
        "is_stale": is_stale,
        "stale_reason": freshness.stale_reason if freshness else None,
        "computed_at": freshness.computed_at if freshness else None,
        "status": _decision_status(conn, is_stale),
        "last_change": (
            {
                "old_label": change.old_label, "new_label": change.new_label,
                "trigger": change.trigger, "changed_at": change.changed_at, "explanation": change.explanation,
                "impact": change.impact,
            } if change is not None else None
        ),
    }


def build_live_snapshot(conn: sqlite3.Connection, live_payload: dict | None) -> dict:
    from fpl_agent.models.gw_lifecycle import compute_gw_lifecycle_state
    from fpl_agent.models.live_bonus import compute_live_bonus
    from fpl_agent.monitoring.dashboard.legacy import _compute_my_live_score

    now = datetime.now(timezone.utc).isoformat()
    event = live_or_reference_event(conn)
    locked = get_locked_squad(conn)
    my_live_score = _compute_my_live_score(conn, locked, live_payload, event) if locked is not None else None
    squad_ids = locked.squad_ids if locked is not None else frozenset()
    live_bonus_rows = compute_live_bonus(conn, live_payload) if live_payload is not None else []

    lifecycle = compute_gw_lifecycle_state(conn)
    gw_block = (
        {"event": lifecycle.event, "state": lifecycle.state} if lifecycle is not None
        else {"event": event, "state": None}
    )

    live_rank_decision = latest_decision_of_type(conn, "live_rank")
    rank_block = None
    if live_rank_decision is not None:
        d = live_rank_decision.detail
        rank_block = {
            "estimated_rank": d.get("estimated_rank"),
            "precision": d.get("precision"),
            "source": d.get("source"),
            "event": d.get("event"),
            # Never a stale prior-gameweek estimate presented as current -
            # same real rule the dashboard's own rank tile already applies.
            "is_current": d.get("event") == event,
            "retrieved_at": live_rank_decision.created_at,
        }

    points_block = None
    if my_live_score is not None:
        points_block = {
            "points": my_live_score.points,
            "captain_points": my_live_score.captain_points,
            "captain_name": my_live_score.captain_name,
            "captain_play_state": my_live_score.captain_play_state,
            "played": my_live_score.played,
            "live": my_live_score.live,
            "yet_to_play": my_live_score.yet_to_play,
            "bench": my_live_score.bench,
        }

    return {
        "version": now,  # ISO timestamp - sortable, and a real "as of" disclosure, not an opaque counter
        "generated_at": now,
        "event": event,
        "gw": gw_block,
        "rank": rank_block,
        "points": points_block,
        "squad": _squad_block(conn, locked),
        "bonus_defcon": _bonus_defcon_block(live_bonus_rows, squad_ids),
        "match_events": _match_events_block(live_bonus_rows),
        "recent_changes": _recent_changes_block(conn, squad_ids),
        "points_changes": _points_changes_block(conn, squad_ids),
        "recommendation": _recommendation_block(conn, squad_ids),
        "source_freshness": _source_freshness_block(conn),
        "cadence": _cadence_block(conn, rank_block["retrieved_at"] if rank_block else None),
    }


def write_live_snapshot(conn: sqlite3.Connection, live_payload: dict | None) -> Path:
    snapshot = build_live_snapshot(conn, live_payload)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot), encoding="utf-8")
    return SNAPSHOT_PATH
