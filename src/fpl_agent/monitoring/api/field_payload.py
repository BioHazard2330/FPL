"""THE FIELD screen's payload: this week's plan, scored against everyone else.

Reads the stored week plan and the stored effective-ownership sample, then asks
`models/rank_engine` what each version of your gameweek (as you set it, the plan
rolled, each single move, the full plan) and each captaincy choice is worth
against the field's average manager, with the spread of outcomes and the
players the field holds that you do not. See that module for the method and its
assumptions. Built once per ten minutes per field and held in memory; a build
simulates about 150 players and takes a few seconds."""
import threading
import time
from datetime import datetime, timezone

from fpl_agent.monitoring.dashboard.context import DashboardContext

_CACHE_LOCK = threading.Lock()
_cache: dict[str, tuple[float, int, dict]] = {}
_TTL_SECONDS = 600.0
_THREATS = 8


def _positions_and_names(conn) -> tuple[dict[int, str], dict[int, dict]]:
    rows = conn.execute(
        "SELECT p.id, p.web_name, p.team_id, t.short_name, t.code, et.singular_name_short AS position "
        "FROM players p JOIN teams t ON t.id = p.team_id JOIN element_types et ON et.id = p.element_type"
    ).fetchall()
    return (
        {r["id"]: r["position"] for r in rows},
        {r["id"]: {"name": r["web_name"], "team_short": r["short_name"], "team_code": r["code"], "position": r["position"]} for r in rows},
    )


def _overall_posture(conn) -> dict | None:
    from fpl_agent.ingestion.my_team import get_my_team_entry_id

    entry = get_my_team_entry_id(conn)
    if entry is None:
        return None
    row = conn.execute(
        "SELECT overall_rank, event FROM my_team_gw_summary WHERE entry_id=? ORDER BY event DESC LIMIT 1", (entry,),
    ).fetchone()
    total = conn.execute("SELECT value FROM app_meta WHERE key='total_players'").fetchone()
    if row is None or total is None or not row["overall_rank"]:
        return None
    n = int(total["value"])
    return {"overall_rank": row["overall_rank"], "total_players": n, "percentile": round(row["overall_rank"] / n, 4), "after_event": row["event"]}


def _model_bias(conn) -> dict | None:
    """How far the current model's settled predictions ran from what players
    scored (all players, not only this squad), with a standard error across
    gameweeks. The edge is a gap between two sums of the same number of slots,
    so a shortfall that is roughly the same per player cancels in it; the points
    column does not, which is why the page prints this beside it. Shown only
    once it spans three gameweeks: one gameweek is its own scoring level."""
    from fpl_agent.models.live_forecast import MIN_BIAS_GAMEWEEKS, MIN_BIAS_SAMPLE, prediction_shortfall

    s = prediction_shortfall(conn)
    if s["n"] < MIN_BIAS_SAMPLE or s["gameweeks"] < MIN_BIAS_GAMEWEEKS:
        return None
    return {
        "n": s["n"], "gameweeks": s["gameweeks"], "bias_per_player": round(s["mean"], 2),
        "standard_error": round(s["standard_error"], 2) if s["standard_error"] is not None else None,
    }


def _ids(lineup_players) -> list[int]:
    return [p["player_id"] if isinstance(p, dict) else p.player_id for p in lineup_players]


def _build(kind: str) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models import rank_engine as re
    from fpl_agent.optimization.week_plan import _lineup, _start_percents, latest_week_plan

    conn = get_connection()
    try:
        stored = latest_week_plan(conn)
        if stored is None:
            return {"status": "no_plan"}
        plan, created_at, decision_id = stored
        field_model = re.build_field(conn, kind, for_event=plan["event"])
        if field_model is None:
            return {"status": "no_sample", "detail": "no effective-ownership sample has been collected this season"}

        event = plan["event"]
        positions, names = _positions_and_names(conn)
        squad = list(plan["squad_ids"])
        moves = plan["moves"]
        plan_squad = set(squad)
        for m in moves:
            plan_squad.discard(m["out"]["player_id"])
            plan_squad.add(m["into"]["player_id"])

        # the top-10k chase is always against the top ten thousand, whichever field the page is showing
        chase_field = field_model if field_model.kind == "top10k" else re.build_field(conn, "top10k", for_event=event)
        wanted = {pid for pid, eo in field_model.eo.items() if eo >= re.MIN_SIMULATED_EO} | set(squad) | plan_squad
        if chase_field is not None:
            wanted |= {pid for pid, eo in chase_field.eo.items() if eo >= re.MIN_SIMULATED_EO}
        trials = re.simulate_players(conn, event, sorted(wanted))
        fpts, coverage = re.field_points(field_model, trials)
        chase_fpts = re.field_points(chase_field, trials)[0] if chase_field is not None else None
        chase_scores: dict[str, object] = {}
        spread = re.population_sd(conn)

        starts = _start_percents(conn, set(squad) | plan_squad)
        cache: dict = {}
        current_xi = {p["player_id"] for p in plan["lineup_now"]["starting"]}

        def lineup_for(squad_set: set[int]):
            return _lineup(conn, squad_set, event, cache, starts, current_xi)

        def evaluate(label: str, key: str, starters, bench, captain, vice, squad_set, move_pairs):
            score = re.score_lineup(trials, positions, starters, bench, captain, vice)
            chase_scores[key] = score
            return {
                "key": key, "label": label, "moves": move_pairs,
                "captain": {"player_id": captain, **names.get(captain, {})} if captain else None,
                "xi": [{"player_id": pid, **names.get(pid, {})} for pid in starters],
                "edge": re.edge_to_dict(re.edge_stats(score, fpts, spread)),
                "mean_points": round(float(score.mean()), 2),
            }, score

        options = []
        by_you = plan.get("lineup_set_by_you")
        if by_you:
            o, _ = evaluate("Your lineup as set", "as_set", _ids(by_you["starting"]), _ids(by_you["bench"]),
                            by_you["captain_id"], by_you["vice_id"], set(squad), [])
            options.append(o)
        now = plan["lineup_now"]
        o, _ = evaluate("Roll: best eleven, no transfers", "roll", _ids(now["starting"]), _ids(now["bench"]), now["captain_id"], now["vice_id"], set(squad), [])
        options.append(o)
        if len(moves) > 1:
            for m in moves:
                squad_set = (set(squad) - {m["out"]["player_id"]}) | {m["into"]["player_id"]}
                lp = lineup_for(squad_set)
                o, _ = evaluate(
                    f"Only {m['out']['name']} to {m['into']['name']}", f"single_{m['into']['player_id']}",
                    _ids(lp.starting), _ids(lp.bench), lp.captain_id, lp.vice_id, squad_set,
                    [{"out": m["out"]["name"], "into": m["into"]["name"]}],
                )
                options.append(o)
        after = plan["lineup_after"]
        o, plan_score = evaluate(
            "The plan" if moves else "The plan (roll)", "plan", _ids(after["starting"]), _ids(after["bench"]),
            after["captain_id"], after["vice_id"], plan_squad, [{"out": m["out"]["name"], "into": m["into"]["name"]} for m in moves],
        )
        options.append(o)
        plan_option = o

        starters = _ids(after["starting"])
        bench = _ids(after["bench"])
        vice_default = after["vice_id"]
        by_xp = sorted(after["starting"], key=lambda p: -p["xp"])
        captains = []
        for p in by_xp:
            pid = p["player_id"]
            vice = vice_default if vice_default != pid else next((q["player_id"] for q in by_xp if q["player_id"] != pid), None)
            score = re.score_lineup(trials, positions, starters, bench, pid, vice)
            chase_scores[f"captain_{pid}"] = score
            captains.append({
                "player_id": pid, **names.get(pid, {}), "mean_points": round(float(trials[pid].mean()), 2) if pid in trials else None,
                "captain_share": round(field_model.captain_share.get(pid, 0.0), 3),
                "field_eo": round(field_model.eo.get(pid, 0.0), 3),
                "edge": re.edge_to_dict(re.edge_stats(score, fpts, spread)),
                "chosen": pid == after["captain_id"],
            })

        mean_pts = {pid: float(arr.mean()) for pid, arr in trials.items()}
        threats = []
        for pid, eo in sorted(field_model.eo.items(), key=lambda kv: -kv[1] * mean_pts.get(kv[0], 0.0)):
            if pid in plan_squad or pid not in trials:
                continue
            arr = trials[pid]
            threats.append({
                "player_id": pid, **names.get(pid, {}), "field_eo": round(eo, 3), "mean_points": round(mean_pts[pid], 2),
                "p_haul": round(float((arr >= 8).mean()), 3), "cost": round(eo * mean_pts[pid], 2),
            })
            if len(threats) >= _THREATS:
                break

        captain_id = after["captain_id"]
        contributions = []
        for pid in starters:
            mult = 2 if pid == captain_id else 1
            eo = field_model.eo.get(pid, 0.0)
            contributions.append({
                "player_id": pid, **names.get(pid, {}), "you": mult, "field_eo": round(eo, 3),
                "mean_points": round(mean_pts.get(pid, 0.0), 2), "edge": round((mult - eo) * mean_pts.get(pid, 0.0), 2),
            })
        contributions.sort(key=lambda c: c["edge"])

        chase_block = None
        if chase_fpts is not None:
            from fpl_agent.models.rank_target import chase

            def vs_top(key: str) -> dict:
                return re.edge_to_dict(re.edge_stats(chase_scores[key], chase_fpts, spread))

            chase_block = chase(
                conn, vs_top("plan"),
                [{**o, "edge": vs_top(o["key"])} for o in options],
                [{**c, "edge": vs_top(f"captain_{c['player_id']}")} for c in captains],
            )

        best_edge = max(captains, key=lambda c: c["edge"]["mean"])
        upside = max((c for c in captains if c["edge"]["mean"] >= best_edge["edge"]["mean"] - 0.5), key=lambda c: c["edge"]["p90"])
        return {
            "status": "ok", "event": event, "n_trials": re.N_TRIALS, "generated_at": datetime.now(timezone.utc).isoformat(),
            "decision_id": decision_id, "plan_computed_at": created_at,
            "field": {
                "kind": field_model.kind, "label": field_model.label, "sample_event": field_model.sample_event,
                "sample_size": field_model.sample_size, "coverage": round(coverage, 3), "spread": round(spread, 1),
            },
            "posture": _overall_posture(conn), "model_bias": _model_bias(conn), "options": options, "plan_option": plan_option,
            "captains": captains, "best_captain_id": best_edge["player_id"], "upside_captain_id": upside["player_id"],
            "threats": threats, "contributions": contributions, "chase": chase_block,
            "axis": {"min": -re.HIST_RANGE, "max": re.HIST_RANGE, "bins": re.HIST_BINS},
        }
    finally:
        conn.close()


def build_field_payload(ctx: DashboardContext, params: dict | None = None) -> dict:
    kind = (params or {}).get("kind", "population")
    if kind not in ("top10k", "population"):
        raise LookupError("kind must be top10k or population")
    from fpl_agent.database.connection import get_connection
    from fpl_agent.optimization.week_plan import latest_week_plan

    conn = get_connection()
    try:
        stored = latest_week_plan(conn)
    finally:
        conn.close()
    current_id = stored[2] if stored else 0
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _cache.get(kind)
        if hit and now - hit[0] < _TTL_SECONDS and hit[1] == current_id:
            return hit[2]
    payload = _build(kind)
    with _CACHE_LOCK:
        _cache[kind] = (time.monotonic(), payload.get("decision_id", 0), payload)
    return payload


build_field_payload.needs_context = False
