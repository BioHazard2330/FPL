"""THE SEASON STORY - `models/season_story.season_story` for the manager's entry."""


def build_story_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.ingestion.my_team import get_my_team_entry_id
    from fpl_agent.models.season_story import season_story

    conn = get_connection()
    try:
        entry = get_my_team_entry_id(conn)
        if entry is None:
            return {"status": "no_entry"}
        return season_story(conn, entry) or {"status": "no_weeks"}
    finally:
        conn.close()
