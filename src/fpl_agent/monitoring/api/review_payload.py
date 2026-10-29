"""THE GAMEWEEK REPORT - `models/gw_review.gameweek_review` for one finished gameweek (`?event=N`, default the latest)."""


def build_review_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.ingestion.my_team import get_my_team_entry_id
    from fpl_agent.models.gw_review import gameweek_review

    conn = get_connection()
    try:
        entry = get_my_team_entry_id(conn)
        if entry is None:
            return {"status": "no_entry"}
        event = (params or {}).get("event")
        if event is None:
            row = conn.execute("SELECT MAX(event) AS e FROM my_team_gw_summary WHERE entry_id = ?", (entry,)).fetchone()
            event = row["e"] if row else None
        if event is None:
            return {"status": "none"}
        review = gameweek_review(conn, entry, int(event))
        if review is None:
            return {"status": "none", "event": int(event)}
        return {"status": "ok", **review}
    finally:
        conn.close()


build_review_payload.needs_context = False  # type: ignore[attr-defined]
