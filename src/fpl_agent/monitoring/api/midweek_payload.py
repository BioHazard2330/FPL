"""MIDWEEK - the squad's and the plan's targets' cup and European matches either side of today, with each player's
part once the lineups are in (`ingestion/midweek_watch.midweek_block`), and the cup events raised in the last week."""


def build_midweek_payload(ctx=None, params: dict | None = None) -> dict:
    from datetime import datetime, timedelta, timezone

    from fpl_agent.database.connection import get_connection
    from fpl_agent.ingestion.midweek_watch import midweek_block
    from fpl_agent.optimization.week_plan import light_squad_state, plan_target_ids

    conn = get_connection()
    try:
        state = light_squad_state(conn)
        squad = set(state["squad_ids"]) if state else set()
        targets = plan_target_ids(conn) - squad
        matches = midweek_block(conn, squad | targets)
        for m in matches:
            for p in m["players"]:
                p["mine"] = p["player_id"] in squad
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        events = [dict(r) for r in conn.execute(
            "SELECT event_type, entity_id AS player_id, severity, fpl_impact, detected_at FROM change_events "
            "WHERE event_type IN ('cup_withdrawal', 'cup_absence') AND detected_at >= ? ORDER BY detected_at DESC", (since,),
        )]
        return {"status": "ok", "matches": matches, "events": events}
    finally:
        conn.close()
