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
    """Real chart-design fix (2026-09-12, direct user report: the raw
    cumulative-points lines for near-tied paths (e.g. 486.3 vs 477.2 over an
    8-GW horizon, ~2% apart) rendered as visually indistinguishable
    overlapping lines on an absolute 0-500pt axis - exactly what a panel
    literally titled "Cumulative Edge" should never do. `y` is now each
    path's cumulative total MINUS the leading path's own cumulative total at
    the same real gameweek - the leading path is therefore always a flat
    zero reference line, and every alternative path's own real edge (or
    deficit) against it is what's actually plotted, matching the panel's
    own name instead of just its own absolute score."""
    raw = []
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
        raw.append({"idx": i, "rank": rank, "points": points, "events": events})

    if not raw:
        return []

    leader_by_gw = {pt["x"]: pt["y"] for pt in raw[0]["points"]}
    series = []
    for r in raw:
        delta_points = [
            {"x": pt["x"], "y": round(pt["y"] - leader_by_gw[pt["x"]], 2) if pt["x"] in leader_by_gw else None}
            for pt in r["points"]
        ]
        series.append({
            "name": f"Path {r['idx']}", "path_idx": r["idx"], "role": "leading" if r["rank"] == 0 else "alt",
            "points": delta_points, "events": r["events"],
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


def _steps_json(steps: list[dict], identity: dict[int, dict], starting_squad_ids: set[int] = frozenset()) -> list[dict]:
    out = []
    prev_squad = set(starting_squad_ids)
    for j, s in enumerate(steps):
        out_id, in_id = s.get("player_out_id"), s.get("player_in_id")
        # Real chip-rebuild squad diff (2026-09-12, direct user report: a
        # wildcard/chip step only ever had `player_out_id`/`player_in_id`
        # (always null for a chip - it's not a single-pair swap), so the
        # frontend had nothing but a bare chip name to show. Diffing this
        # step's real `resulting_squad_ids` against the squad going INTO it
        # surfaces the actual players in/out - real for a wildcard's full
        # rebuild, empty (nothing to show) for a step that doesn't change
        # the squad (bench boost/triple captain), same real field either way.
        players_in: list[dict] = []
        players_out: list[dict] = []
        resulting = s.get("resulting_squad_ids")
        if resulting is not None:
            resulting_set = set(resulting)
            in_ids = sorted(resulting_set - prev_squad)
            out_ids = sorted(prev_squad - resulting_set)
            players_in = [identity[pid] for pid in in_ids if pid in identity]
            players_out = [identity[pid] for pid in out_ids if pid in identity]
            prev_squad = resulting_set
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
            "players_in": players_in,
            "players_out": players_out,
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


def _matches_the_real_played_chip(path: dict, reference_event: int | None, played_chip: str | None) -> bool:
    """A path's own first step is what it recommends doing AT the anchor
    gameweek - but once the user has actually played a chip on the real FPL
    site for that gameweek, that decision is no longer open. A beam-search
    path built without knowing that (its `used_chip_names` constraint is
    season-level - "not burned yet" - not "already committed this specific
    gameweek") can still propose a DIFFERENT action at the anchor event,
    which depicts a reality that already didn't happen. `steps` skips a
    gameweek entirely when the real optimal action there is a pure roll, so
    "no step at the anchor event" also counts as a mismatch whenever a chip
    was really played."""
    if played_chip is None or reference_event is None:
        return True
    steps = path.get("steps") or []
    anchor_step = next((s for s in steps if s.get("event") == reference_event), None)
    if anchor_step is None:
        return False
    chip = anchor_step.get("chip_played")
    return chip is not None and chip.lower() == played_chip.lower()


def build_plan_payload(ctx: DashboardContext) -> dict:
    sd = ctx.sd
    if ctx.locked is None:
        return {"has_plan": False, "reason": "No locked squad - lock a squad to plan your strategy."}
    if sd is None or not sd.get("paths"):
        return {"has_plan": False, "reason": "Run `fpl strategic-plan` to see the multi-GW path search."}

    from fpl_agent.database.connection import get_connection

    paths = sd["paths"]
    # Real correctness fix (2026-09-12, direct user report: the strategy
    # grid showed alternative paths proposing WILDCARD/BENCH BOOST at GW4 as
    # if that were still an open decision, when the user had already played
    # Free Hit for real that gameweek - those paths depict a reality that
    # can no longer happen). Never applied when nothing was actually played
    # (`ctx.played_chip_this_event is None`), and falls back to the
    # unfiltered list if every path would otherwise be discarded (the beam
    # search genuinely found nothing consistent with reality - a real,
    # rare gap worth surfacing as-is rather than returning an empty plan).
    reality_consistent = [
        p for p in paths if _matches_the_real_played_chip(p, ctx.reference_event, ctx.played_chip_this_event)
    ]
    # `delta_vs_second_best` (which `near_tie_state` reads) was computed
    # against the ORIGINAL beam's real runner-up - once that runner-up has
    # been filtered out for contradicting the real played chip, "CLEAR
    # LEAD"/"NEAR TIE" would describe a lead over a competitor that can no
    # longer happen. Only meaningful when a genuine alternative survives.
    filtered_some = len(reality_consistent) < len(paths)
    if reality_consistent:
        paths = reality_consistent
    horizon_gw = sd.get("horizon_gw")
    primary_indices, family_of = primary_path_indices(paths)
    leader = paths[0]
    tie = near_tie_state(leader) if not (filtered_some and len(paths) == 1) else None

    conn = get_connection()
    try:
        leader_conf = path_confidence(conn, leader)
        # Real starting squad for the whole plan - the same squad every
        # path's own step 0 is a delta against (Free Hit reversion already
        # applied upstream in `build_strategic_plan`'s own input, see
        # `optimization/locked_squad.py::resolve_planning_squad`).
        starting_squad_ids = set(sd.get("squad_ids") or [])
        needed_ids: set[int] = set()
        for i in primary_indices:
            prev_squad = starting_squad_ids
            for s in paths[i - 1].get("steps") or []:
                for key in ("player_out_id", "player_in_id"):
                    pid = s.get(key)
                    if pid is not None:
                        needed_ids.add(pid)
                # Real gap found 2026-09-12 (direct user report: "it says
                # wildcard but doesn't even show the wildcard" - a chip step
                # rebuilds many players at once, never just one pair, so the
                # single player_out_id/player_in_id fields above are always
                # null for it). `resulting_squad_ids` is the real full 15-
                # man squad this step leaves the path in - diffing it
                # against the squad going INTO this step surfaces exactly
                # which real players came in/out, for a chip step or any
                # other step alike.
                resulting = s.get("resulting_squad_ids")
                if resulting is not None:
                    resulting_set = set(resulting)
                    needed_ids |= (resulting_set - prev_squad) | (prev_squad - resulting_set)
                    prev_squad = resulting_set
        identity = _player_identity_map(conn, needed_ids, ctx.team_codes)

        path_rows = []
        for i in primary_indices:
            p = paths[i - 1]
            conf = path_confidence(conn, p)
            siblings = family_of[i][1:]
            path_rows.append({
                "idx": i,
                "descriptor": path_descriptor(
                    p, played_chip=ctx.played_chip_this_event, reference_event=ctx.reference_event
                ),
                "score": p.get("path_total"),
                "confidence": _CONFIDENCE_LABEL.get(conf, "-") if conf else "-",
                "is_leading": i == 1,
                "sibling_count": len(siblings),
                "sibling_scores": [paths[s - 1].get("path_total") for s in siblings],
                "steps": _steps_json(p.get("steps") or [], identity, starting_squad_ids),
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
    leader_chip_steps = [s for s in (leader.get("steps") or []) if s.get("chip_played")]
    leader_already_played = bool(
        leader_chip_steps
        and ctx.played_chip_this_event is not None
        and leader_chip_steps[0]["event"] == ctx.reference_event
        and leader_chip_steps[0]["chip_played"].lower() == ctx.played_chip_this_event.lower()
    )

    return {
        "has_plan": True,
        "horizon_gw": horizon_gw,
        "leader": {
            "descriptor": path_descriptor(
                leader, played_chip=ctx.played_chip_this_event, reference_event=ctx.reference_event
            ),
            "already_played_chip": leader_already_played,
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
