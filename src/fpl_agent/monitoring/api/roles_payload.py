"""The role engine (`models/roles.py`): with `?team=ID` that club's depth chart and set-piece takers; without, the
league's changes (role moves, into and out of the eleven, new corner takers) and the players FPL lists deeper than
they play."""


def build_roles_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models import roles
    from fpl_agent.monitoring.api.photos import attach_photo_codes

    params = params or {}
    conn = get_connection()
    try:
        team = params.get("team")
        if team:
            tid = int(team)
            from fpl_agent.models.manager_brain import manager_brain

            out = {"depth": roles.depth_chart(conn, tid), "set_pieces": roles.set_pieces(conn, tid), "manager": manager_brain(conn, tid)}
        else:
            out = {"changes": roles.league_changes(conn), "out_of_position": roles.out_of_position(conn)}
        return attach_photo_codes(conn, out)
    finally:
        conn.close()


build_roles_payload.needs_context = False
