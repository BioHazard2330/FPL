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
        from fpl_agent.models import pundit_views as pv

        event = _reference_event(conn)
        entry = get_my_team_entry_id(conn)
        views = [{"id": r[0], "name": r[1], "factor": r[2], "from": r[3], "through": r[4], "reason": r[5]} for r in conn.execute(
            "SELECT v.id, p.web_name, v.factor, v.from_event, v.through_event, v.reason FROM pundit_view v JOIN players p ON p.id = v.player_id "
            "WHERE v.revoked_at IS NULL AND v.through_event >= ? ORDER BY v.id", (event,))] if pv._has_table(conn) else []
        view_board = pv.ledger(conn)
        board = ledger(conn, entry) if entry is not None else {"rows": []}
        found = latest_call(conn, event)
        if found is None:
            return {"status": "none", "event": event, "ledger": board, "views": views, "view_ledger": view_board}
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
            "plan_captain": (plan.get("lineup_after") or {}).get("captain_id"), "ledger": board, "views": views, "view_ledger": view_board,
        })
    finally:
        conn.close()


build_punditcall_payload.needs_context = False
