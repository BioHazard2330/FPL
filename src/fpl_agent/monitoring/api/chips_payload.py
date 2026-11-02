"""THE CHIP CALENDAR - `models/chip_calendar.chip_calendar` for the manager's entry and squad."""


def build_chips_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.ingestion.my_team import get_my_team_entry_id
    from fpl_agent.models.chip_calendar import chip_calendar
    from fpl_agent.optimization.week_plan import light_squad_state

    conn = get_connection()
    try:
        state = light_squad_state(conn)
        return chip_calendar(conn, get_my_team_entry_id(conn), set(state["squad_ids"]) if state else set())
    finally:
        conn.close()
