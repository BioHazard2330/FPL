"""PLAN screen JSON payload (2026-09-08, Phase 8.3). Reads exactly the same
real fields `monitoring/dashboard/plan.py`/`live_charts.py`'s trajectory/
contribution charts already render - reuses `plan.py`'s own pure helpers
(`path_descriptor`, `path_confidence`, `near_tie_state`, `primary_path_
indices`) rather than re-deriving them. Never recomputes the strategic
plan itself - `sd` is already the cached decision object every other real
consumer reads."""
import re

from fpl_agent.database.decisions import latest_decision_of_type
from fpl_agent.monitoring.dashboard.context import DashboardContext
from fpl_agent.monitoring.dashboard.legacy import _chip_display_name
from fpl_agent.monitoring.dashboard.plan import (
    _CONFIDENCE_LABEL,
    near_tie_state,
    path_confidence,
    path_descriptor,
    primary_path_indices,
)


def _trajectory_series(paths: list[dict], shown_indices: list[int]) -> list[dict]:
    series = []
    for rank, i in enumerate(shown_indices):
        p = paths[i - 1]
        steps = p.get("steps") or []
        if not steps:
            continue
        points, events = [], []
        running = 0.0
        for s in steps:
            gw = s["event"]
            running += s.get("gw_ev") or 0.0
            points.append({"x": gw, "y": round(running, 2)})
            action = s.get("action", "ROLL")
            if action != "ROLL":
                label = s["chip_played"].upper() if s.get("chip_played") else action
                events.append({"x": gw, "label": label})
        series.append({
            "name": f"Path {i}", "path_idx": i, "role": "leading" if rank == 0 else "alt",
            "points": points, "events": events,
        })
    return series


def _steps_json(steps: list[dict]) -> list[dict]:
    out = []
    for j, s in enumerate(steps):
        out.append({
            "event": s["event"],
            "action": s.get("action", "ROLL"),
            "chip_played": _chip_display_name(s["chip_played"]).upper() if s.get("chip_played") else None,
            "uses_hit": bool(s.get("uses_hit")),
            "gw_ev": round(s["gw_ev"], 2) if s.get("gw_ev") is not None else None,
            "player_out_id": s.get("player_out_id"),
            "player_in_id": s.get("player_in_id"),
            "is_locked": j == 0,
        })
    return out


def _sensitivity_rows(conn) -> list[dict]:
    audit = latest_decision_of_type(conn, "decision_audit")
    if audit is None:
        return []
    falsifiers = audit.detail.get("falsifiers") or []
    rows = []
    for f in falsifiers:
        m = re.search(r"~(\d+)%", f.get("description", ""))
        if m:
            rows.append({"label": f["description"].split(" reverts to ROLL")[0], "pct": int(m.group(1))})
    rows.sort(key=lambda r: r["pct"])
    return rows[:5]


def build_plan_payload(ctx: DashboardContext) -> dict:
    sd = ctx.sd
    if ctx.locked is None:
        return {"has_plan": False, "reason": "No locked squad - lock a squad to plan your strategy."}
    if sd is None or not sd.get("paths"):
        return {"has_plan": False, "reason": "Run `fpl strategic-plan` to see the multi-GW path search."}

    from fpl_agent.database.connection import get_connection

    paths = sd["paths"]
    horizon_gw = sd.get("horizon_gw")
    primary_indices, family_of = primary_path_indices(paths)
    leader = paths[0]
    tie = near_tie_state(leader)

    conn = get_connection()
    try:
        leader_conf = path_confidence(conn, leader)
        path_rows = []
        for i in primary_indices:
            p = paths[i - 1]
            conf = path_confidence(conn, p)
            siblings = family_of[i][1:]
            path_rows.append({
                "idx": i,
                "descriptor": path_descriptor(p),
                "score": p.get("path_total"),
                "confidence": _CONFIDENCE_LABEL.get(conf, "-") if conf else "-",
                "is_leading": i == 1,
                "sibling_count": len(siblings),
                "sibling_scores": [paths[s - 1].get("path_total") for s in siblings],
                "steps": _steps_json(p.get("steps") or []),
                "final_free_transfers": p.get("final_free_transfers"),
                "final_bank_m": round((p.get("final_bank_tenths") or 0) / 10, 1),
                "horizon_breakdown": p.get("horizon_breakdown"),
                "chip_steps": [
                    {"event": s["event"], "chip": _chip_display_name(s["chip_played"]).upper()}
                    for s in (p.get("steps") or []) if s.get("chip_played")
                ],
            })
        sensitivity = _sensitivity_rows(conn)
    finally:
        conn.close()

    shown_indices = primary_indices[:4]
    trajectory_series = _trajectory_series(paths, shown_indices)

    return {
        "has_plan": True,
        "horizon_gw": horizon_gw,
        "leader": {
            "descriptor": path_descriptor(leader),
            "tie": tie,
            "confidence": _CONFIDENCE_LABEL.get(leader_conf, "-") if leader_conf else "-",
            "score": leader.get("path_total"),
            "delta_vs_roll": leader.get("delta_vs_roll"),
            "roll_total": sd.get("roll_total"),
        },
        "trajectory_series": trajectory_series,
        "paths": path_rows,
        "sensitivity": sensitivity,
    }
