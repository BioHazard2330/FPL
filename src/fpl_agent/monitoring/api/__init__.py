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
from fpl_agent.monitoring.api.leagues_payload import build_leagues_payload
from fpl_agent.monitoring.api.livecone_payload import build_livecone_payload
from fpl_agent.monitoring.api.livestory_payload import build_live_story
from fpl_agent.monitoring.api.match_payload import build_match_report
from fpl_agent.monitoring.api.matchweek_payload import build_matchweek_payload
from fpl_agent.monitoring.api.myteam_payload import build_my_team_payload
from fpl_agent.monitoring.api.plan_payload import build_plan_payload
from fpl_agent.monitoring.api.previews_payload import build_previews_payload
from fpl_agent.monitoring.api.profile_payload import build_club_profile, build_player_profile
from fpl_agent.monitoring.api.receipts_payload import build_receipts_payload
from fpl_agent.monitoring.api.components_payload import build_components_payload
from fpl_agent.monitoring.api.album_payload import build_album_payload
from fpl_agent.monitoring.api.eye_payload import build_eye_payload
from fpl_agent.monitoring.api.prices_payload import build_prices_payload
from fpl_agent.monitoring.api.midweek_payload import build_midweek_payload
from fpl_agent.monitoring.api.cohort_payload import build_cohort_payload
from fpl_agent.monitoring.api.decide_payload import build_decide_payload, build_locks_payload
from fpl_agent.monitoring.api.getme_payload import build_getme_payload
from fpl_agent.monitoring.api.map_payload import build_map_payload
from fpl_agent.monitoring.api.story_payload import build_story_payload
from fpl_agent.monitoring.api.chips_payload import build_chips_payload
from fpl_agent.monitoring.api.workload_payload import build_workload_payload
from fpl_agent.monitoring.api.commentary_payload import build_commentary_payload
from fpl_agent.monitoring.api.chipdraft_payload import build_chipdraft_payload
from fpl_agent.monitoring.api.playbyplay_payload import build_playbyplay_payload
from fpl_agent.monitoring.api.daemon_payload import build_daemon_payload
from fpl_agent.monitoring.api.review_payload import build_review_payload
from fpl_agent.monitoring.api.scout_payload import build_scout_payload
from fpl_agent.monitoring.api.signals_payload import build_signals_payload
from fpl_agent.monitoring.api.squadnews_payload import build_squad_news
from fpl_agent.monitoring.api.table_payload import build_table_payload
from fpl_agent.monitoring.api.viewplan_payload import build_view_plan
from fpl_agent.monitoring.api.weekplan_payload import build_week_plan_payload
from fpl_agent.monitoring.api.punditcall_payload import build_punditcall_payload
from fpl_agent.monitoring.api.supercomputer_payload import build_supercomputer_payload
from fpl_agent.monitoring.api.swing_payload import build_swing_payload
from fpl_agent.monitoring.api.whatif_payload import build_whatif_payload

API_BUILDERS = {
    "command": build_command_payload,
    "myteam": build_my_team_payload,
    "plan": build_plan_payload,
    "football": build_football_payload,
    "matchweek": build_matchweek_payload,
    "scout": build_scout_payload,
    "signals": build_signals_payload,
    "components": build_components_payload,
    "review": build_review_payload,
    "prices": build_prices_payload,
    "midweek": build_midweek_payload,
    "cohort": build_cohort_payload,
    "decide": build_decide_payload,
    "locks": build_locks_payload,
    "getme": build_getme_payload,
    "map": build_map_payload,
    "story": build_story_payload,
    "chips": build_chips_payload,
    "workload": build_workload_payload,
    "commentary": build_commentary_payload,
    "chipdraft": build_chipdraft_payload,
    "playbyplay": build_playbyplay_payload,
    "daemon": build_daemon_payload,
    "album": build_album_payload,
    "eye": build_eye_payload,
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
    "swing": build_swing_payload,
    "supercomputer": build_supercomputer_payload,
    "punditcall": build_punditcall_payload,
    "whatif": build_whatif_payload,
    "viewplan": build_view_plan,
    "squadnews": build_squad_news,
    "leagues": build_leagues_payload,
    "livestory": build_live_story,
    "explorer": build_explorer_payload,
    "projection": build_projection_payload,
    # Parameterised profiles (`?id=`) - the dispatcher passes `params` to a
    # builder that declares it, and turns a LookupError into a real 404.
    "club": build_club_profile,
    "match": build_match_report,
    "player": build_player_profile,
}
