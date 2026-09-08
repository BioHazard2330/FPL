"""Real regression coverage for the PLAN JSON payload builder (2026-09-08,
Phase 8.3). The populated-`sd` path was manually verified against real
production data (a real GW4 Free Hit -> Wildcard -> Bench Boost path,
`docs/UI_REDESIGN_DECISIONS.md`'s Phase 8.3 entry) - seeding a real
`strategic_plan` decision journal entry here would duplicate that
verification with a synthetic beam-search result; this test locks in the
honest empty-state contract instead, matching `test_api_command_payload.py`'s
own no-op-locked-squad coverage."""
import json

from fpl_agent.monitoring.api.plan_payload import _player_identity_map, _steps_json, build_plan_payload
from fpl_agent.monitoring.dashboard.context import build_dashboard_context
from test_optimization_squad import _seed


def test_plan_payload_is_honest_with_no_locked_squad(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    ctx = build_dashboard_context(db_conn)
    payload = build_plan_payload(ctx)
    json.dumps(payload)
    assert payload["has_plan"] is False
    assert "reason" in payload


def test_steps_json_carries_real_transfer_player_identity(db_conn):
    """Real regression (2026-09-08, art-direction pass v3, direct user
    follow-up: "more football" - the Strategy Rail used to be pure text for
    a transfer leg, e.g. "Botman -> Andersen", with zero shirt imagery since
    a `PlanStep` only ever carried a raw `player_out_id`/`player_in_id`).
    `_player_identity_map` resolves real name/team_code/position for every
    player id appearing across the shown paths in one batched query - a
    unit test against the real helpers directly (this file's own established
    convention is not to fabricate a full beam-search `strategic_plan`
    decision just to exercise a JSON-shaping helper)."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    team_codes = {r["id"]: r["code"] for r in db_conn.execute("SELECT id, code FROM teams").fetchall()}

    identity = _player_identity_map(db_conn, {10, 30}, team_codes)
    assert identity[10]["name"] == "P10"
    assert identity[10]["position"] == "DEF"  # element_type=2 in the shared fixture pool
    assert identity[10]["team_code"] == team_codes[1]  # player 10 is team_id=1 in the shared fixture pool
    assert identity[30]["position"] == "FWD"  # element_type=4

    steps = [{
        "event": 5, "action": "Botman -> Andersen", "chip_played": None, "uses_hit": False,
        "gw_ev": 1.2, "player_out_id": 10, "player_in_id": 30,
    }]
    out = _steps_json(steps, identity)
    assert out[0]["player_out"]["name"] == "P10"
    assert out[0]["player_in"]["name"] == "P30"
    assert out[0]["player_out"]["team_code"] == team_codes[1]

    # A player id absent from `identity` (e.g. a real query miss) degrades
    # honestly to `None`, never a fabricated placeholder identity.
    out_missing = _steps_json(
        [{"event": 6, "action": "X -> Y", "chip_played": None, "uses_hit": False, "gw_ev": None,
          "player_out_id": 999, "player_in_id": None}],
        identity,
    )
    assert out_missing[0]["player_out"] is None
    assert out_missing[0]["player_in"] is None
    json.dumps(out)
    json.dumps(out_missing)
