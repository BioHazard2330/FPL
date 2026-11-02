"""COMMENTARY - the league's text commentary for one FPL fixture (`ingestion/commentary.commentary`)."""


def build_commentary_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.ingestion.commentary import commentary

    raw = (params or {}).get("fixture")
    raw = raw[0] if isinstance(raw, list) else raw
    try:
        fixture_id = int(raw)
    except (TypeError, ValueError):
        return {"status": "bad_request"}
    conn = get_connection()
    try:
        return commentary(conn, fixture_id)
    finally:
        conn.close()
