"""THE RECEIPTS - the optimizer measured against YOUR decisions, in points.

Direct user statement: "i still dont use the optimizer to date for my
decisions", followed by the right instruction - measure what it suggested
against what you actually did.

**The first version of this screen measured the wrong thing.** It reported
the optimizer's chosen action against *its own rejected runner-up*
(`models/decision_calibration.py`), and on that basis showed +22.0 net,
5-1, 83.3%. Neither side of that comparison is what the user did, so it
could not answer the only question that matters, and it pointed the
opposite way from the truth. Run properly against the real squads
(`models/counterfactual_ledger.py`), the optimizer is **behind** over the
same period.

So the headline here is the counterfactual ledger: your real score, its
recommended squad's score, and the do-nothing baseline, gameweek by
gameweek. The old internal-consistency numbers are still carried, clearly
labelled for what they actually are, because "did it beat its own second
choice" is a real question - just not this one.

Honesty rules enforced here rather than left to the UI:

- **A gameweek with no logged recommendation is absent, not zero.** GW5 has
  none at all (a wildcard was played and the pipeline recorded nothing), and
  the payload says so.
- **Totals only span comparable gameweeks.** Summing across gaps would
  flatter whichever side happened to have fewer of them.
- **A chip you played that it never suggested is recorded on the row**, so a
  lopsided gap is never read as a like-for-like loss.
- **ROLL is always shown.** A recommendation that scores exactly what doing
  nothing scored is the single most useful thing this screen can surface,
  and it has already happened once.
"""
import threading
import time

from fpl_agent.models.counterfactual_ledger import build_counterfactual_ledger, ledger_totals
from fpl_agent.models.decision_calibration import decision_backtest_summary
from fpl_agent.monitoring.dashboard.context import DashboardContext

_MIN_MEANINGFUL_SAMPLE = 8

# The ledger scores every finished gameweek against FPL's per-event live
# endpoint, one network call each, on every request - 2.8s for six gameweeks
# and growing by a call per week, from a screen COMMAND also reads every two
# minutes. A finished gameweek's points only move on a bonus correction, so a
# few minutes of caching costs nothing a reader would see.
_CACHE_LOCK = threading.Lock()
_cached_payload: dict | None = None
_cached_at: float = 0.0
_TTL_SECONDS = 600.0

_CHIP_LABEL = {
    "3xc": "Triple Captain",
    "freehit": "Free Hit",
    "wildcard": "Wildcard",
    "bboost": "Bench Boost",
}


def _calibration_block(conn) -> dict | None:
    """MODEL vs REALITY: every settled prediction against its outcome.

    One dot per player-gameweek from `prediction_outcomes` - the projection
    the model committed to BEFORE the deadline and the points that actually
    landed. Nothing is recomputed; a dot is a frozen prediction and a real
    result. The band is the same measured error `models/materiality.py`
    derives the transfer bar from, drawn so a reader can see what "inside
    the noise" looks like against real dots rather than take the number on
    faith. Absent (None) until there are settled rows to draw.
    """
    import statistics

    from fpl_agent.models.expected_points import MODEL_VERSION

    query = (
        "SELECT po.player_id, p.web_name, po.event, po.predicted_median, po.predicted_floor, "
        "       po.predicted_ceiling, po.predicted_confidence, po.actual_points, po.actual_minutes, po.model_version "
        "FROM prediction_outcomes po JOIN players p ON p.id = po.player_id "
        "WHERE po.predicted_median IS NOT NULL AND po.actual_points IS NOT NULL {extra} "
        "ORDER BY po.event, po.player_id"
    )
    current = conn.execute(query.format(extra="AND po.model_version = ?"), (MODEL_VERSION,)).fetchall()
    rows = current if len(current) >= _MIN_MEANINGFUL_SAMPLE * 5 else conn.execute(query.format(extra="")).fetchall()
    if not rows:
        return None
    version = MODEL_VERSION if rows is current else "all versions"

    points = [{
        "player_id": r["player_id"], "player": r["web_name"], "event": r["event"],
        "predicted": round(float(r["predicted_median"]), 2),
        "floor": round(float(r["predicted_floor"]), 2) if r["predicted_floor"] is not None else None,
        "ceiling": round(float(r["predicted_ceiling"]), 2) if r["predicted_ceiling"] is not None else None,
        "confidence": r["predicted_confidence"],
        "actual": float(r["actual_points"]),
        "minutes": r["actual_minutes"],
        # Inside the model's own floor..ceiling band, when it stated one.
        "inside_band": (
            r["predicted_floor"] is not None and r["predicted_ceiling"] is not None
            and float(r["predicted_floor"]) <= float(r["actual_points"]) <= float(r["predicted_ceiling"])
        ),
    } for r in rows]

    errors = [pt["actual"] - pt["predicted"] for pt in points]
    mae = statistics.mean(abs(e) for e in errors)
    bias = statistics.mean(errors)
    stdev = statistics.pstdev(errors) if len(errors) > 1 else 0.0
    banded = [pt for pt in points if pt["floor"] is not None and pt["ceiling"] is not None]
    inside = sum(1 for pt in banded if pt["inside_band"])

    return {
        "version": version,
        "n": len(points),
        "mae": round(mae, 2),
        "bias": round(bias, 2),
        "error_stdev": round(stdev, 2),
        "band_coverage_pct": round(inside / len(banded) * 100, 1) if banded else None,
        "band_n": len(banded),
        "points": points,
        "note": (
            "Each dot is one player in one gameweek: the median the model committed to before the "
            "deadline against the points that landed. The diagonal is a perfect call. The shaded "
            "band is one standard deviation of the model's own measured error - the same figure the "
            "transfer bar is derived from. Coverage is how often the real result fell inside the "
            "floor-to-ceiling range the model stated for that player."
        ),
    }


def build_receipts_payload(ctx: DashboardContext) -> dict:
    global _cached_payload, _cached_at
    with _CACHE_LOCK:
        if _cached_payload is not None and (time.monotonic() - _cached_at) < _TTL_SECONDS:
            return _cached_payload
    payload = _build_receipts_payload_uncached(ctx)
    with _CACHE_LOCK:
        _cached_payload = payload
        _cached_at = time.monotonic()
    return payload


def _build_receipts_payload_uncached(ctx: DashboardContext) -> dict:
    from fpl_agent.database.connection import get_connection

    conn = get_connection()
    try:
        rows = build_counterfactual_ledger(conn)
        if not rows:
            return {
                "has_record": False,
                "reason": (
                    "Not enough synced history yet. This fills in once there are two "
                    "consecutive gameweeks of real squads to compare."
                ),
            }

        totals = ledger_totals(rows)
        names = {r[0]: r[1] for r in conn.execute("SELECT id, web_name FROM players")}

        def action_label(row) -> str | None:
            if row.optimizer_action in (None, "ROLL"):
                return row.optimizer_action
            try:
                out_id, in_id = (int(x) for x in row.optimizer_action.split(" -> "))
            except (ValueError, AttributeError):
                return row.optimizer_action
            return f"{names.get(out_id, out_id)} → {names.get(in_id, in_id)}"

        ledger = [{
            "event": r.event,
            "your_points": r.your_points,
            "your_chip": r.your_chip,
            "your_chip_label": _CHIP_LABEL.get(r.your_chip or "", r.your_chip),
            "your_transfers": r.your_transfers,
            "optimizer_points": r.optimizer_points,
            "optimizer_action": action_label(r),
            "roll_points": r.roll_points,
            "delta_vs_you": r.delta_vs_you,
            "followed": r.followed,
            "note": r.note,
            "plan_points": r.plan_points,
            "plan_action": r.plan_action,
            "plan_followed": r.plan_followed,
            # A recommendation worth exactly what doing nothing was worth.
            # Called out explicitly because it is invisible in any
            # win/loss framing and is the clearest possible evidence that
            # the engine does not know when to roll.
            "worthless_vs_roll": (
                r.optimizer_points is not None
                and r.roll_points is not None
                and r.optimizer_points <= r.roll_points
            ),
        } for r in rows]

        internal = [{
            "kind": s.decision_kind,
            "n": s.n,
            "win_rate_pct": round((s.win_rate or 0.0) * 100, 1),
            "mean_advantage": s.mean_advantage,
            "thin": s.n < _MIN_MEANINGFUL_SAMPLE,
        } for s in decision_backtest_summary(conn)]

        never_rolled = all(
            r.optimizer_action not in (None, "ROLL") for r in rows if r.optimizer_action is not None
        )

        calibration = _calibration_block(conn)

        return {
            "has_record": True,
            "calibration": calibration,
            "replay": _replay_block(),
            "headline": {
                "your_total": totals.your_total,
                "your_total_all_events": totals.your_total_all_events,
                "optimizer_total": totals.optimizer_total,
                "roll_total": totals.roll_total,
                "delta": totals.delta,
                "comparable_events": totals.comparable_events,
                "events": totals.events,
                "followed_count": totals.followed_count,
                "recommendations_logged": totals.recommendations_logged,
                "plan_events": totals.plan_events,
                "plan_total": totals.plan_total,
                "plan_your_total": totals.plan_your_total,
                "plan_roll_total": totals.plan_roll_total,
                # Signed from the optimizer's point of view: negative means
                # your own decisions scored more.
                "optimizer_ahead": (totals.delta or 0) > 0,
            },
            "ledger": ledger,
            "flags": {
                "never_recommended_roll": never_rolled,
                "missing_recommendations": totals.events - totals.recommendations_logged,
                "followed_none": totals.followed_count == 0,
            },
            "internal_consistency": internal,
            "method": (
                "YOURS is your real score, validated against FPL's own recorded total for every "
                "finished gameweek. OPTIMIZER is your previous gameweek's squad with the transfer it "
                "actually recommended at that deadline, scored this gameweek. ROLL is that squad "
                "carried forward untouched. The optimizer column holds your previous starting eleven "
                "and captain, because it only ever proposed a transfer, never a lineup - so this "
                "isolates the transfer decision and does not credit or blame it for your own XI and "
                "captaincy changes."
            ),
            "correction": (
                "An earlier version of this screen compared the optimizer against its own rejected "
                "runner-up and reported it winning. Both sides of that comparison were hypothetical. "
                "This measures against what you actually did."
            ),
        }
    finally:
        conn.close()


# Reads its own tables only - never waits on the full dashboard context.
build_receipts_payload.needs_context = False  # type: ignore[attr-defined]


def _replay_block() -> dict | None:
    """The week plan's policy replayed over past seasons (`fpl plan-replay`, `backtesting/plan_replay.py`), if it has run."""
    import json

    from fpl_agent.config import DATA_DIR

    path = DATA_DIR / "plan_replay.json"
    if not path.exists():
        return None
    try:
        seasons = json.loads(path.read_text(encoding="utf-8")).get("seasons", [])
    except (OSError, ValueError):
        return None
    if not seasons:
        return None
    total = {k: sum(s["totals"][k] for s in seasons) for k in ("plan", "swap", "hold")}
    return {
        "seasons": [{k: s[k] for k in ("season", "rounds", "totals", "transfers", "hits")} for s in seasons],
        "total": total,
        "beat_swap": sum(1 for s in seasons if s["totals"]["plan"] > s["totals"]["swap"]),
        "beat_hold": sum(1 for s in seasons if s["totals"]["plan"] > s["totals"]["hold"]),
    }

