"""One player's god's-eye panel (`models/gods_eye.py`) with the pundit's written call on him (`models/judgements.py`)."""


def build_godseye_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.gods_eye import player_eye
    from fpl_agent.models.judgements import for_player, latest

    pid = int((params or {}).get("player") or 0)
    conn = get_connection()
    try:
        eye = player_eye(conn, pid) if pid else None
        if eye is None:
            return {"status": "none"}
        return {"status": "ok", **eye, "judgement": for_player(latest(conn), pid)}
    finally:
        conn.close()


build_godseye_payload.needs_context = False
