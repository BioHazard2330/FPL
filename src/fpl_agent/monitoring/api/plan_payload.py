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


def _player_identity_map(conn, player_ids: set[int], team_codes: dict[int, int]) -> dict[int, dict]:
    """Real name/team_code/position for a real set of player ids appearing as
    a transfer leg's out/in target somewhere in the shown paths (2026-09-08,
    art-direction pass v3, direct user follow-up: "more football" - the
    Strategy Rail had zero shirt imagery because this payload never carried
    team identity for a transfer leg's players, only their raw ids). One
    batched query, not one per leg."""
    if not player_ids:
        return {}
    placeholders = ",".join("?" for _ in player_ids)
    rows = conn.execute(
        f"SELECT id, web_name, team_id, element_type FROM players WHERE id IN ({placeholders})",
        tuple(player_ids),
    ).fetchall()
    position_by_type = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    return {
        r["id"]: {
            "player_id": r["id"],
            "name": r["web_name"],
            "team_code": team_codes.get(r["team_id"]),
            "position": position_by_type.get(r["element_type"]),
        }
        for r in rows
    }


def _steps_json(steps: list[dict], identity: dict[int, dict]) -> list[dict]:
    out = []
    for j, s in enumerate(steps):
        out_id, in_id = s.get("player_out_id"), s.get("player_in_id")
        out.append({
            "event": s["event"],
            "action": s.get("action", "ROLL"),
            "chip_played": _chip_display_name(s["chip_played"]).upper() if s.get("chip_played") else None,
            "uses_hit": bool(s.get("uses_hit")),
            "gw_ev": round(s["gw_ev"], 2) if s.get("gw_ev") is not None else None,
            "player_out_id": out_id,
            "player_in_id": in_id,
            "player_out": identity.get(out_id) if out_id is not None else None,
            "player_in": identity.get(in_id) if in_id is not None else None,
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
        needed_ids: set[int] = set()
        for i in primary_indices:
            for s in paths[i - 1].get("steps") or []:
                for key in ("player_out_id", "player_in_id"):
                    pid = s.get(key)
                    if pid is not None:
                        needed_ids.add(pid)
        identity = _player_identity_map(conn, needed_ids, ctx.team_codes)

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
                "steps": _steps_json(p.get("steps") or [], identity),
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
