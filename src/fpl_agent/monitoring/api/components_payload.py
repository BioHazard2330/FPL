"""HOW THE MODEL DID, BY PART - `models/component_skill.component_report` for the System screen."""


def build_components_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.component_skill import component_report

    conn = get_connection()
    try:
        return component_report(conn)
    finally:
        conn.close()


build_components_payload.needs_context = False  # type: ignore[attr-defined]
