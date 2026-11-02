"""WORKLOAD - minutes and running over the last 7, 14 and 28 days for the squad and the plan's targets, league and cup
(`ingestion/workload.workload_block`)."""


def build_workload_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.ingestion.workload import workload_block
    from fpl_agent.optimization.week_plan import light_squad_state, plan_target_ids

    conn = get_connection()
    try:
        state = light_squad_state(conn)
        squad = list(state["squad_ids"]) if state else []
        targets = [p for p in plan_target_ids(conn) if p not in squad]
        rows = workload_block(conn, squad + targets)
        for r in rows:
            r["mine"] = r["player_id"] in squad
        return {"status": "ok", "players": rows}
    finally:
        conn.close()
