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
from fpl_agent.monitoring.api.atlas_payload import build_atlas_payload
from fpl_agent.monitoring.api.audit_payload import build_audit_payload
from fpl_agent.monitoring.api.compare_payload import build_compare_payload, build_players_index, build_projection_payload
from fpl_agent.monitoring.api.desk_payload import build_desk_payload
from fpl_agent.monitoring.api.command_payload import build_command_payload
from fpl_agent.monitoring.api.field_payload import build_field_payload
from fpl_agent.monitoring.api.explorer_payload import build_explorer_payload
from fpl_agent.monitoring.api.football_payload import build_football_payload
from fpl_agent.monitoring.api.livecone_payload import build_livecone_payload
from fpl_agent.monitoring.api.match_payload import build_match_report
from fpl_agent.monitoring.api.matchweek_payload import build_matchweek_payload
from fpl_agent.monitoring.api.myteam_payload import build_my_team_payload
from fpl_agent.monitoring.api.plan_payload import build_plan_payload
from fpl_agent.monitoring.api.previews_payload import build_previews_payload
from fpl_agent.monitoring.api.profile_payload import build_club_profile, build_player_profile
from fpl_agent.monitoring.api.receipts_payload import build_receipts_payload
from fpl_agent.monitoring.api.scout_payload import build_scout_payload
from fpl_agent.monitoring.api.signals_payload import build_signals_payload
from fpl_agent.monitoring.api.table_payload import build_table_payload
from fpl_agent.monitoring.api.weekplan_payload import build_week_plan_payload
from fpl_agent.monitoring.api.whatif_payload import build_whatif_payload

API_BUILDERS = {
    "command": build_command_payload,
    "myteam": build_my_team_payload,
    "plan": build_plan_payload,
    "football": build_football_payload,
    "matchweek": build_matchweek_payload,
    "scout": build_scout_payload,
    "signals": build_signals_payload,
    "advanced": build_advanced_payload,
    "receipts": build_receipts_payload,
    "atlas": build_atlas_payload,
    "table": build_table_payload,
    "weekplan": build_week_plan_payload,
    "desk": build_desk_payload,
    "previews": build_previews_payload,
    "players": build_players_index,
    "compare": build_compare_payload,
    "field": build_field_payload,
    "audit": build_audit_payload,
    "livecone": build_livecone_payload,
    "whatif": build_whatif_payload,
    "explorer": build_explorer_payload,
    "projection": build_projection_payload,
    # Parameterised profiles (`?id=`) - the dispatcher passes `params` to a
    # builder that declares it, and turns a LookupError into a real 404.
    "club": build_club_profile,
    "match": build_match_report,
    "player": build_player_profile,
}
