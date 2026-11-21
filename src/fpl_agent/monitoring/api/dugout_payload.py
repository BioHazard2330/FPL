"""The Dugout (`models/dugout.py`): every club's style, game-state behaviour and manager habits; `?team=ID` adds how each
of that club's players is used, `?players=ID,...` how the given players are used."""


def build_dugout_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.dugout import dugout, player_usage
    from fpl_agent.monitoring.api.photos import attach_photo_codes
    from fpl_agent.optimization.week_plan import light_squad_state

    params = params or {}
    conn = get_connection()
    try:
        out = dugout(conn)
        team = params.get("team")
        if team:
            out["usage"] = player_usage(conn, team_id=int(team))
        state = light_squad_state(conn)
        squad = list(state["squad_ids"]) if state else []
        out["squad_usage"] = player_usage(conn, player_ids=squad) if squad else []
        return attach_photo_codes(conn, out)
    finally:
        conn.close()


build_dugout_payload.needs_context = False
