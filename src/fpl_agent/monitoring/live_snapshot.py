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


def _bonus_defcon_block(conn: sqlite3.Connection, live_payload: dict | None, squad_ids: frozenset[int]) -> list[dict]:
    """Real, cheap - `compute_live_bonus` is a pure computation over the
    already-fetched `live_payload` (no network call of its own), filtered to
    the locked squad so this stays small. `None` fields (e.g. `defcon_reached`
    for a GKP) pass through honestly, never defaulted to a misleading value."""
    if live_payload is None or not squad_ids:
        return []
    from fpl_agent.models.live_bonus import compute_live_bonus

    rows = compute_live_bonus(conn, live_payload)
    return [
        {
            "player_id": r.player_id, "web_name": r.web_name, "minutes": r.minutes,
            "provisional_bonus": r.provisional_bonus, "confirmed_bonus": r.confirmed_bonus,
            "defensive_contribution": r.defensive_contribution, "defcon_reached": r.defcon_reached,
        }
        for r in rows if r.player_id in squad_ids
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


def _recommendation_block(conn: sqlite3.Connection, squad_ids: frozenset[int]) -> dict | None:
    """Real decision-freshness + change-explanation, both already-cheap real
    reads (no beam search, no re-derivation) - see decision_freshness.py/
    decision_change.py's own docstrings."""
    from fpl_agent.database.decisions import latest_decision_of_type
    from fpl_agent.models.decision_change import latest_recommendation_change
    from fpl_agent.models.decision_freshness import assess_recommendation_freshness

    strategic_decision = latest_decision_of_type(conn, "strategic_plan")
    freshness = assess_recommendation_freshness(conn, strategic_decision, squad_ids) if strategic_decision else None
    change = latest_recommendation_change(conn, squad_ids)
    if freshness is None and change is None:
        return None
    return {
        "is_stale": freshness.is_stale if freshness else None,
        "stale_reason": freshness.stale_reason if freshness else None,
        "computed_at": freshness.computed_at if freshness else None,
        "last_change": (
            {
                "old_label": change.old_label, "new_label": change.new_label,
                "trigger": change.trigger, "changed_at": change.changed_at, "explanation": change.explanation,
            } if change is not None else None
        ),
    }


def build_live_snapshot(conn: sqlite3.Connection, live_payload: dict | None) -> dict:
    from fpl_agent.monitoring.dashboard.legacy import _compute_my_live_score

    now = datetime.now(timezone.utc).isoformat()
    event = live_or_reference_event(conn)
    locked = get_locked_squad(conn)
    my_live_score = _compute_my_live_score(conn, locked, live_payload, event) if locked is not None else None
    squad_ids = locked.squad_ids if locked is not None else frozenset()

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
        "rank": rank_block,
        "points": points_block,
        "bonus_defcon": _bonus_defcon_block(conn, live_payload, squad_ids),
        "recent_changes": _recent_changes_block(conn, squad_ids),
        "recommendation": _recommendation_block(conn, squad_ids),
    }


def write_live_snapshot(conn: sqlite3.Connection, live_payload: dict | None) -> Path:
    snapshot = build_live_snapshot(conn, live_payload)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot), encoding="utf-8")
    return SNAPSHOT_PATH
