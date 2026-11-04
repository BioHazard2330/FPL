"""The pundit's call for the next gameweek with faces and names, beside the plan's moves, and the ledger (`models/pundit_call.py`)."""


def build_punditcall_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.ingestion.my_team import get_my_team_entry_id
    from fpl_agent.models.fixtures import _reference_event
    from fpl_agent.models.pundit_call import latest_call, ledger
    from fpl_agent.monitoring.api.photos import attach_photo_codes
    from fpl_agent.monitoring.api.whatif_payload import _briefs
    from fpl_agent.optimization.week_plan import latest_week_plan

    conn = get_connection()
    try:
        event = _reference_event(conn)
        entry = get_my_team_entry_id(conn)
        board = ledger(conn, entry) if entry is not None else {"rows": []}
        found = latest_call(conn, event)
        if found is None:
            return {"status": "none", "event": event, "ledger": board}
        call, made_at = found
        ids = [int(p) for m in call.get("moves", []) for p in (m["out"], m["in"])] + [int(call["captain"]), int(call["vice"])]
        brief = _briefs(conn, list(dict.fromkeys(ids)))
        stored = latest_week_plan(conn)
        plan = stored[0] if stored and stored[0].get("event") == event else {}
        plan_in = {m["into"]["player_id"] for m in plan.get("moves", [])}
        moves = [{"out": brief[int(m["out"])], "into": brief[int(m["in"])], "why": m.get("why"), "with_plan": int(m["in"]) in plan_in} for m in call.get("moves", [])]
        return attach_photo_codes(conn, {
            "status": "ok", "event": event, "made_at": made_at, "headline": call.get("headline"), "moves": moves, "hold": call.get("hold", []),
            "captain": {**brief[int(call["captain"])], "why": call.get("captain_why")}, "vice": brief[int(call["vice"])], "differs": call.get("differs"), "watch": call.get("watch", []),
            "plan_moves": [{"out": m["out"]["name"], "into": m["into"]["name"]} for m in plan.get("moves", [])],
            "plan_captain": (plan.get("lineup_after") or {}).get("captain_id"), "ledger": board,
        })
    finally:
        conn.close()


build_punditcall_payload.needs_context = False
