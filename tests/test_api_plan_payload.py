"""Real regression coverage for the PLAN JSON payload builder (2026-09-08,
Phase 8.3). The populated-`sd` path was manually verified against real
production data (a real GW4 Free Hit -> Wildcard -> Bench Boost path,
`docs/UI_REDESIGN_DECISIONS.md`'s Phase 8.3 entry) - seeding a real
`strategic_plan` decision journal entry here would duplicate that
verification with a synthetic beam-search result; this test locks in the
honest empty-state contract instead, matching `test_api_command_payload.py`'s
own no-op-locked-squad coverage."""
import json

from fpl_agent.monitoring.api.plan_payload import build_plan_payload
from fpl_agent.monitoring.dashboard.context import build_dashboard_context
from test_optimization_squad import _seed


def test_plan_payload_is_honest_with_no_locked_squad(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    ctx = build_dashboard_context(db_conn)
    payload = build_plan_payload(ctx)
    json.dumps(payload)
    assert payload["has_plan"] is False
    assert "reason" in payload
