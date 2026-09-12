"""Real regression coverage for the PLAN JSON payload builder (2026-09-08,
Phase 8.3). The populated-`sd` path was manually verified against real
production data (a real GW4 Free Hit -> Wildcard -> Bench Boost path,
`docs/UI_REDESIGN_DECISIONS.md`'s Phase 8.3 entry) - seeding a real
`strategic_plan` decision journal entry here would duplicate that
verification with a synthetic beam-search result; this test locks in the
honest empty-state contract instead, matching `test_api_command_payload.py`'s
own no-op-locked-squad coverage."""
import json

from fpl_agent.monitoring.api.plan_payload import (
    _matches_the_real_played_chip,
    _player_identity_map,
    _steps_json,
    _trajectory_series,
    build_plan_payload,
)
from fpl_agent.monitoring.dashboard.context import build_dashboard_context
from test_optimization_squad import _seed


def test_plan_payload_is_honest_with_no_locked_squad(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    ctx = build_dashboard_context(db_conn)
    payload = build_plan_payload(ctx)
    json.dumps(payload)
    assert payload["has_plan"] is False
    assert "reason" in payload


def test_matches_the_real_played_chip_true_when_no_chip_was_played():
    path = {"steps": [{"event": 4, "chip_played": "wildcard"}]}
    assert _matches_the_real_played_chip(path, reference_event=4, played_chip=None) is True


def test_matches_the_real_played_chip_true_when_first_step_matches():
    path = {"steps": [{"event": 4, "chip_played": "freehit"}, {"event": 6, "chip_played": "wildcard"}]}
    assert _matches_the_real_played_chip(path, reference_event=4, played_chip="freehit") is True


def test_matches_the_real_played_chip_false_when_anchor_step_proposes_a_different_chip():
    path = {"steps": [{"event": 4, "chip_played": "wildcard"}]}
    assert _matches_the_real_played_chip(path, reference_event=4, played_chip="freehit") is False


def test_matches_the_real_played_chip_false_when_path_implicitly_rolls_the_anchor_event():
    path = {"steps": [{"event": 6, "chip_played": "wildcard"}]}  # no step at GW4 = implicit roll
    assert _matches_the_real_played_chip(path, reference_event=4, played_chip="freehit") is False


def test_build_plan_payload_drops_paths_that_contradict_the_real_played_chip(db_conn):
    """Real regression (2026-09-12, direct user report: the strategy grid
    showed WILDCARD/BENCH BOOST at GW4 as live alternatives when Free Hit
    had already been played for real that gameweek)."""
    import dataclasses

    from fpl_agent.monitoring.dashboard.context import build_dashboard_context
    from test_optimization_squad import _seed

    _seed(db_conn, budget_tenths=950, club_limit=4)
    fake_sd = {
        "horizon_gw": 6,
        "paths": [
            {"steps": [{"event": 4, "action": "PLAY WILDCARD", "chip_played": "wildcard", "gw_ev": 60.0}], "path_total": 60.0, "delta_vs_roll": 10.0},
            {"steps": [{"event": 4, "action": "PLAY FREE HIT", "chip_played": "freehit", "gw_ev": 57.1}], "path_total": 57.1, "delta_vs_roll": 8.0},
        ],
    }
    ctx = build_dashboard_context(db_conn)
    ctx = dataclasses.replace(ctx, sd=fake_sd, locked=object(), reference_event=4, played_chip_this_event="freehit")

    payload = build_plan_payload(ctx)
    assert payload["has_plan"] is True
    assert payload["leader"]["descriptor"].lower().startswith("free hit")
    assert all(row["descriptor"].lower().startswith("free hit") for row in payload["paths"])


def test_trajectory_series_plots_delta_vs_the_leading_path_not_raw_cumulative_pts():
    """Real chart-design regression (2026-09-12, direct user report: near-
    tied paths' raw cumulative totals render as indistinguishable
    overlapping lines on an absolute scale). The leading path (rank 0, shown
    first in `shown_indices`) must always plot as a flat zero line; an
    alternative path's own `y` at each gw is its real deficit/edge against
    the leader, not its own raw score."""
    paths = [
        {"steps": [{"event": 4, "gw_ev": 50.0, "action": "ROLL"}, {"event": 5, "gw_ev": 50.0, "action": "ROLL"}]},
        {"steps": [{"event": 4, "gw_ev": 48.0, "action": "ROLL"}, {"event": 5, "gw_ev": 47.0, "action": "ROLL"}]},
    ]
    series = _trajectory_series(paths, [1, 2])

    leader, alt = series[0], series[1]
    assert leader["role"] == "leading" and alt["role"] == "alt"
    assert [pt["y"] for pt in leader["points"]] == [0.0, 0.0]
    # alt: GW4 cumulative 48 vs leader's 50 (-2); GW5 cumulative 95 vs 100 (-5)
    assert [pt["y"] for pt in alt["points"]] == [-2.0, -5.0]


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
