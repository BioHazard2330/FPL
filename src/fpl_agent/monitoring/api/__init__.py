"""JSON API payload builders for the React frontend (2026-09-08, Phase 8.2
Stage 2). One module per screen, each a thin, deliberate JSON-shaping pass
over the SAME real objects `monitoring/dashboard/*.py`'s HTML renderers
already read from a `DashboardContext` (`monitoring/dashboard/context.py`) -
never a second computation of a decision, projection, or recommendation. See
docs/FRONTEND_MIGRATION_PLAN.md for the full Python<->React boundary.

`API_BUILDERS` maps a screen slug (the `/api/<slug>` route in
`live/sse_server.py`) to its payload builder - added to as each screen is
migrated (Stage 3 onward), never all at once."""
from fpl_agent.monitoring.api.advanced_payload import build_advanced_payload
from fpl_agent.monitoring.api.command_payload import build_command_payload
from fpl_agent.monitoring.api.football_payload import build_football_payload
from fpl_agent.monitoring.api.myteam_payload import build_my_team_payload
from fpl_agent.monitoring.api.plan_payload import build_plan_payload
from fpl_agent.monitoring.api.scout_payload import build_scout_payload

API_BUILDERS = {
    "command": build_command_payload,
    "myteam": build_my_team_payload,
    "plan": build_plan_payload,
    "football": build_football_payload,
    "scout": build_scout_payload,
    "advanced": build_advanced_payload,
}
