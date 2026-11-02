"""VERSUS THE 10K - the manager's season against the managers ranked around 10,000 (`models/cohort_compare.py`)."""


def build_cohort_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.ingestion.my_team import get_my_team_entry_id
    from fpl_agent.models.cohort_compare import season_compare

    conn = get_connection()
    try:
        entry = get_my_team_entry_id(conn)
        if entry is None:
            return {"status": "no_entry"}
        return season_compare(conn, entry) or {"status": "no_cohort"}
    finally:
        conn.close()
