"""THE WEEK PLAN - this gameweek's transfers, lineup and armband as one payload.

Reads the plan `optimization/week_plan.py` stored in the decision journal; it
never solves anything itself, so it answers in milliseconds and does not wait
on the dashboard context. Everything the screen needs to draw a move (shirt,
crest, next fixtures) is attached here so the client resolves nothing.

A plan the squad has outgrown is still served, marked stale with the reasons,
because blanking the screen would hide that a recommendation once existed. The
client decides how loudly to say so.
"""
from datetime import datetime, timezone

from fpl_agent.monitoring.dashboard.context import DashboardContext


def _team_codes(conn, team_ids: set[int]) -> dict[int, int]:
    if not team_ids:
        return {}
    marks = ",".join("?" * len(team_ids))
    return {r["id"]: r["code"] for r in conn.execute(f"SELECT id, code FROM teams WHERE id IN ({marks})", tuple(team_ids))}


def _with_code(player: dict, codes: dict[int, int]) -> dict:
    return {**player, "team_code": codes.get(player.get("team_id"))}


def lineup_changes(as_set: dict | None, best: dict) -> dict | None:
    """What it takes to turn the lineup the manager has set into the best one
    from the same fifteen: who comes into the eleven, who leaves it, the
    armband, and what the difference is worth in expected points."""
    if as_set is None:
        return None
    set_ids = {p["player_id"] for p in as_set["starting"]}
    best_ids = {p["player_id"] for p in best["starting"]}
    names = {p["player_id"]: p for p in as_set["starting"] + as_set["bench"] + best["starting"] + best["bench"]}
    swaps_in = [names[i] for i in sorted(best_ids - set_ids, key=lambda i: -names[i]["xp"])]
    swaps_out = [names[i] for i in sorted(set_ids - best_ids, key=lambda i: names[i]["xp"])]
    return {
        "bring_in": swaps_in,
        "take_out": swaps_out,
        "captain_from": names.get(as_set["captain_id"]),
        "captain_to": names.get(best["captain_id"]),
        "vice_from": names.get(as_set["vice_id"]),
        "vice_to": names.get(best["vice_id"]),
        "xp_gain": round(best["xp_total"] - as_set["xp_total"], 2),
        "worth_changing": bool(swaps_in) or as_set["captain_id"] != best["captain_id"],
    }


def build_week_plan_payload(ctx: DashboardContext) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.monitoring.api.fixture_context import fixture_context_by_team_code
    from fpl_agent.optimization.week_plan import latest_week_plan, week_plan_staleness

    conn = get_connection()
    try:
        stored = latest_week_plan(conn)
        if stored is None:
            return {"status": "none"}
        detail, created_at, decision_id = stored
        reasons = week_plan_staleness(conn, detail, created_at)

        team_ids: set[int] = set()
        for move in detail["moves"] + detail["declined"]:
            team_ids.add(move["out"]["team_id"])
            team_ids.add(move["into"]["team_id"])
        for key in ("lineup_now", "lineup_after", "lineup_set_by_you"):
            lineup = detail.get(key)
            if lineup:
                team_ids.update(p["team_id"] for p in lineup["starting"] + lineup["bench"])
        codes = _team_codes(conn, team_ids)

        def coded_move(m: dict) -> dict:
            return {**m, "out": _with_code(m["out"], codes), "into": _with_code(m["into"], codes)}

        def coded_lineup(lineup: dict | None) -> dict | None:
            if lineup is None:
                return None
            return {
                **lineup,
                "starting": [_with_code(p, codes) for p in lineup["starting"]],
                "bench": [_with_code(p, codes) for p in lineup["bench"]],
            }

        lineup_now = coded_lineup(detail["lineup_now"])
        lineup_after = coded_lineup(detail["lineup_after"])
        lineup_set = coded_lineup(detail.get("lineup_set_by_you"))

        def squad_block(lineup: dict) -> dict:
            def tile(p: dict) -> dict:
                return {
                    "player_id": p["player_id"], "name": p["name"], "position": p["position"],
                    "team_code": p["team_code"], "median": p["xp"],
                }

            return {
                "action": "week plan",
                "starting": [tile(p) for p in lineup["starting"]],
                "bench": [tile(p) for p in lineup["bench"]],
                "captain_id": lineup["captain_id"],
                "vice_id": lineup["vice_id"],
            }

        def captain_block(lineup: dict) -> dict | None:
            starters = {p["player_id"]: p for p in lineup["starting"]}
            best = starters.get(lineup["captain_id"])
            if best is None:
                return None
            rest = sorted((p for i, p in starters.items() if i != best["player_id"]), key=lambda p: -p["xp"])

            def brief(p: dict) -> dict:
                return {
                    "player_id": p["player_id"], "name": p["name"], "median": p["xp"], "floor": p.get("floor"),
                    "ceiling": p.get("ceiling"), "team_code": p["team_code"], "position": p["position"],
                }

            second = rest[0] if rest else None
            return {
                "verdict": "KEEP", "verdict_name": best["name"], "robustness": None, "best": brief(best),
                "second": brief(second) if second else None,
                "edge": round(best["xp"] - second["xp"], 2) if second else None, "edge_driver": None,
                "note": lineup.get("captain_note"),
            }

        age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(created_at.replace("Z", "+00:00"))).total_seconds() / 3600
        return {
            "status": "stale" if reasons else "current",
            "stale_reasons": reasons,
            "decision_id": decision_id,
            "computed_at": created_at,
            "age_hours": round(age_hours, 1),
            "event": detail["event"],
            "horizon": detail["horizon"],
            "free_transfers": detail["free_transfers"],
            "free_transfers_known": detail["free_transfers_known"],
            "bank_tenths": detail["bank_tenths"],
            "roll_total": detail["roll_total"],
            "plan_total": detail["plan_total"],
            "gain_vs_roll": detail["gain_vs_roll"],
            "min_move_gain": detail["min_move_gain"],
            "moves": [coded_move(m) for m in detail["moves"]],
            "declined": [coded_move(m) for m in detail["declined"]],
            "curve": detail["curve"],
            "ft_after": detail["ft_after"],
            "bank_after_tenths": detail["bank_after_tenths"],
            "affordability": detail["affordability"],
            "road_ahead": detail.get("road_ahead"),
            "chip_outlook": detail.get("chip_outlook"),
            "proven_optimal": detail["proven_optimal"],
            "notes": detail["notes"],
            "lineup_now": lineup_now,
            "lineup_after": lineup_after,
            "lineup_set_by_you": lineup_set,
            "doctor": lineup_changes(lineup_set, lineup_now),
            "doctor_after_moves": lineup_changes(lineup_set, lineup_after),
            "action_squad": squad_block(lineup_after),
            "captain": captain_block(lineup_after),
            "fixtures": fixture_context_by_team_code(conn, team_ids),
        }
    finally:
        conn.close()


build_week_plan_payload.needs_context = False
