"""Real regression coverage for the MY TEAM JSON payload builder (2026-09-08,
Phase 8.2 Stage 3). Same convention `test_api_command_payload.py` already
established - seed a real DB state, call the builder, assert on real fields."""
import json

from fpl_agent.ingestion.my_team import set_my_team_entry_id
from fpl_agent.monitoring.api.myteam_payload import build_my_team_payload
from fpl_agent.monitoring.dashboard.context import build_dashboard_context
from test_optimization_locked_squad import _seed_real_picks
from test_optimization_squad import _seed


def test_myteam_payload_falls_back_to_the_optimizer_recommendation_with_no_squad_locked(db_conn):
    """Matches the old HTML dashboard's own real behavior (`context.py`'s
    `else` branch) - no locked squad still shows a real pitch, just the
    optimizer's own recommended one, never a blank/empty state."""
    _seed(db_conn, budget_tenths=950, club_limit=4)

    ctx = build_dashboard_context(db_conn)
    payload = build_my_team_payload(ctx)

    json.dumps(payload)
    assert payload["has_squad"] is True
    assert payload["bar"]["pitch_heading"] == "Optimizer Recommendation"


def test_myteam_payload_reflects_the_real_locked_squad(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    set_my_team_entry_id(db_conn, 7378572)
    _seed_real_picks(db_conn, captain_id=30, vice_id=20)
    db_conn.commit()

    ctx = build_dashboard_context(db_conn)
    payload = build_my_team_payload(ctx)

    json.dumps(payload)
    assert payload["has_squad"] is True
    assert payload["bar"]["squad_value_m"] == round(ctx.squad_value_m, 1)
    all_starting_ids = {p["player_id"] for pos in payload["positions"] for p in pos["players"]}
    assert 30 in all_starting_ids  # the real captain must actually be on the pitch
    captain_rows = [p for pos in payload["positions"] for p in pos["players"] if p["is_captain"]]
    assert len(captain_rows) == 1
    assert captain_rows[0]["player_id"] == 30
    bench_ids = {p["player_id"] for p in payload["bench"]}
    assert bench_ids  # a real bench must be present
    assert all_starting_ids.isdisjoint(bench_ids)
