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
        if event is not None:
            review = gameweek_review(conn, entry, int(event))
        else:
            # The newest gameweek with a report: right after a deadline the new gameweek is in the history with nothing
            # to read yet, and the page went blank instead of showing the last one (2026-11-21).
            review = None
            for (e,) in conn.execute("SELECT DISTINCT event FROM my_team_gw_summary WHERE entry_id = ? ORDER BY event DESC LIMIT 3", (entry,)):
                event = e
                review = gameweek_review(conn, entry, int(e))
                if review is not None:
                    break
        if event is None:
            return {"status": "none"}
        if review is None:
            return {"status": "none", "event": int(event)}
        return {"status": "ok", **review}
    finally:
        conn.close()


build_review_payload.needs_context = False  # type: ignore[attr-defined]
