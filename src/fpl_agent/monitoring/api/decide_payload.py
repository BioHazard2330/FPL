"""The Decider (`models/decider.py`): `/api/decide?ideas=` builds the cards, `/api/locks` reads the locked calls alone."""
from fpl_agent.models.projection_memo import projection_memo
from fpl_agent.monitoring.api.photos import attach_photo_codes


def build_decide_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.decider import decide, parse_ideas

    conn = get_connection()
    try:
        try:
            ideas = parse_ideas((params or {}).get("ideas"))
            with projection_memo(conn):
                return attach_photo_codes(conn, decide(conn, ideas))
        except LookupError as e:
            return {"status": "bad_request", "reason": str(e)}
    finally:
        conn.close()


def build_locks_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.decider import locks_block
    from fpl_agent.models.fixtures import _reference_event

    conn = get_connection()
    try:
        return {"status": "ok", **locks_block(conn, _reference_event(conn), deep=False)}
    finally:
        conn.close()


build_decide_payload.needs_context = False
build_locks_payload.needs_context = False
