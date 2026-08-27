"""Regression test for the real chip-mapping bug found in a direct
product audit (2026-08-29): the Plan timeline / Squad preview rendered
`chip_schedule` (the separate `schedule_chips` Monte Carlo DP cross-check,
`optimization/chips.py`) as if it were the winning path's own chip choice,
while the path descriptor/tab label used a DIFFERENT source
(`step.chip_played`, the real beam-searched `TransferSequence`'s own
in-path chip). When the two computations disagreed on GW or chip type
(a real, expected outcome - they are independent algorithms answering
different questions, see CLAUDE.md's own documented distinction), the
rendered dashboard showed mismatched chip/GW combinations across panels.

Fix: `chip_schedule` is no longer read by `plan.py`/`squad.py` at all.
Every chip badge/summary on these two workspaces is now derived directly
from that path's own `steps[].chip_played` - one object, no second source
to disagree with it. This test proves it by constructing an `sd` where
`chip_schedule` names a DIFFERENT GW/chip than the path's own steps, and
asserting the disagreeing value never appears anywhere in the rendered
output."""
from fpl_agent.monitoring.dashboard import plan, squad
from fpl_agent.monitoring.dashboard.legacy import _normalize_strategic_detail
from test_dashboard import _locked_and_decision, _seed


def _make_sd_with_disagreeing_chip_schedule(chip_event: int, chip_name: str):
    """Path 1 plays `chip_name` at `chip_event` (its own real steps). The
    logged `chip_schedule` (independent DP) deliberately recommends a
    DIFFERENT chip at a DIFFERENT GW - the real disagreement shape found
    live. If any rendering path still reads `chip_schedule`, the wrong
    GW/chip (GW9 BBOOST) will leak into the output."""
    steps = [
        {"event": chip_event, "action": f"PLAY {chip_name.upper()}", "chip_played": chip_name,
         "player_out_id": None, "player_in_id": None, "uses_hit": False},
        {"event": chip_event + 1, "action": "ROLL", "chip_played": None,
         "player_out_id": None, "player_in_id": None, "uses_hit": False},
    ]
    path = {
        "total_net_ev": 642.12, "path_total": 642.12, "delta_vs_roll": 30.0, "delta_vs_leader": 0.0,
        "final_free_transfers": 1, "final_bank_tenths": 5, "steps": steps,
    }
    return _normalize_strategic_detail({
        "horizon_gw": 8, "note": "test", "immediate_vs_strategic_differ": False,
        "horizon_comparison": [{"horizon_gw": 8, "opening_action": f"PLAY {chip_name.upper()}", "total_net_ev": 642.12, "path_total": 642.12, "delta_vs_roll": 30.0}],
        "best_path": path,
        "paths": [path],
        # Deliberately disagreeing independent cross-check - must never
        # surface as if it were this path's own chip state.
        "chip_schedule": {
            "entries": [{"event": 9, "chip_name": "bboost", "expected_marginal_value": 12.3, "why_now": "test"}],
            "advisory_hit_recommendations": [],
        },
    })


def test_plan_timeline_never_shows_the_disagreeing_dp_cross_check(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    locked, _ = _locked_and_decision(db_conn)
    sd = _make_sd_with_disagreeing_chip_schedule(chip_event=2, chip_name="wildcard")

    result = plan.render_plan_workspace(db_conn, sd, locked, set(locked.squad_ids))

    # The path's real chip state (GW2 WILDCARD) is present.
    assert "GW2" in result
    assert "WILDCARD" in result
    # The disagreeing DP cross-check (GW9 BBOOST) must never leak in.
    assert "GW9" not in result
    assert "BBOOST" not in result


def test_plan_timeline_chip_badge_is_on_the_correct_event_node(db_conn):
    """Every rendered chip badge must sit on ITS OWN event's timeline node -
    not merely appear somewhere in the page. Proves path+event alignment,
    not just presence."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    locked, _ = _locked_and_decision(db_conn)
    sd = _make_sd_with_disagreeing_chip_schedule(chip_event=4, chip_name="3xc")

    result = plan.render_plan_workspace(db_conn, sd, locked, set(locked.squad_ids))

    gw4_node_start = result.index("data-event='4'")
    gw5_node_start = result.index("data-event='5'")
    gw4_node = result[gw4_node_start:gw5_node_start]
    assert "3XC" in gw4_node
    gw5_node = result[gw5_node_start:]
    # GW5 is a plain ROLL step in this fixture - no chip badge belongs there.
    assert "chip-badge" not in gw5_node.split("</button>")[0]


def test_squad_projected_preview_never_shows_the_disagreeing_dp_cross_check(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    locked, _ = _locked_and_decision(db_conn)
    sd = _make_sd_with_disagreeing_chip_schedule(chip_event=2, chip_name="wildcard")

    result = squad.render_squad_workspace(
        db_conn, locked=locked, sd=sd, pitch_heading="Squad", pitch_html="<div></div>",
        squad_error_html="", headline_xp=50.0, squad_value_m=100.0, bank_m=0.5,
        captain_name="Test Captain", vice_name="Test Vice", xp_summary_label="xP",
        actual_points_label="",
    )

    assert "WILDCARD" in result
    assert "BBOOST" not in result


def test_squad_projected_preview_chip_badge_on_correct_event_block(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    locked, _ = _locked_and_decision(db_conn)
    sd = _make_sd_with_disagreeing_chip_schedule(chip_event=4, chip_name="freehit")

    result = squad.render_squad_workspace(
        db_conn, locked=locked, sd=sd, pitch_heading="Squad", pitch_html="<div></div>",
        squad_error_html="", headline_xp=50.0, squad_value_m=100.0, bank_m=0.5,
        captain_name="Test Captain", vice_name="Test Vice", xp_summary_label="xP",
        actual_points_label="",
    )

    # `data-event='N' hidden` uniquely picks the squad-state-block (the pills
    # above it share the same `data-event` attribute but no `hidden` flag).
    gw4_start = result.index("data-event='4' hidden")
    gw5_start = result.index("data-event='5' hidden")
    assert "FREEHIT" in result[gw4_start:gw5_start]
    gw5_end = result.index("</div></div>", gw5_start)
    assert "chip-badge" not in result[gw5_start:gw5_end]
