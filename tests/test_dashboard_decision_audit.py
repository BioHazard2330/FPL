from fpl_agent.database.decisions import log_decision
from fpl_agent.monitoring.dashboard.legacy import _decision_audit_html


def _seed_minimal(conn):
    now = "2026-01-01T00:00:00Z"
    conn.execute(
        f"INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        f"is_current, is_next, updated_at) VALUES (1,'GW1','{now}',0,1,0,0,1,'{now}')"
    )
    conn.commit()


def test_decision_audit_panel_shows_empty_state_when_never_run(db_conn):
    _seed_minimal(db_conn)

    result = _decision_audit_html(db_conn)

    assert "No adversarial decision audit run yet" in result
    assert "fpl decision-audit" in result


def _fake_audit_detail():
    return {
        "event": 2,
        "causal_chain": [{"label": "STARTING ACTION", "detail": "Tzolis -> Tavernier"}],
        "action_audit": [
            {"label": "Tzolis -> Tavernier", "kind": "transfer", "horizon_results": {3: 12.06, 5: 20.0, 8: 40.0},
             "opportunity_cost": "n/a - this is the winning action", "confidence": "MEDIUM", "robustness": "ROBUST",
             "main_reason_rejected": None},
            {"label": "ROLL", "kind": "roll", "horizon_results": {3: 8.0, 5: 15.0, 8: 30.0},
             "opportunity_cost": "-10.0 pts vs the winner over 8GW", "confidence": None, "robustness": None,
             "main_reason_rejected": "real full-horizon (8GW) path_total is +10.0 pts behind the winner"},
        ],
        "stress_tests": [
            {"dimension": "ATTACKING_INVOLVEMENT", "magnitude": 0.15, "baseline_delta": 12.06, "stressed_delta": 9.5,
             "decision_flips": False, "note": "OUT player's attacking involvement +15%, IN player's -15%: +12.06 -> +9.50 xP net"},
        ],
        "falsifiers": [
            {"description": "Tzolis -> Tavernier reverts to ROLL if attacking involvement moves ~53% against the swap",
             "threshold_note": "analytic threshold from the real component breakdown"},
        ],
        "league_wide": {"candidate_pool_scope": "note", "breakout_count": 3, "differential_count": 2, "trap_count": 1,
                         "chosen_in_is_trap": False, "top_breakouts": [], "top_differentials": []},
        "scorecard": {
            "data_quality": "MEDIUM", "model_quality": "ROBUST", "football_evidence": "NO DISAGREEMENT",
            "market_evidence": "NO TRAP FLAG", "decision_robustness": "ROBUST", "counterfactual_stability": "ROBUST",
            "information_sufficiency": "not assessed", "final_decision": "ACT", "confidence": "MEDIUM",
            "why_trust": ["clear margin over the runner-up"], "why_might_not_trust": ["no specific real weakness identified"],
            "what_would_change_my_mind": ["Tzolis -> Tavernier reverts to ROLL if attacking involvement moves ~53%"],
        },
    }


def test_decision_audit_panel_renders_compact_falsifier_and_collapsed_full_trace(db_conn):
    _seed_minimal(db_conn)
    log_decision(db_conn, "decision_audit", "Tzolis -> Tavernier  [ACT/MEDIUM]  robustness=ROBUST", _fake_audit_detail())
    db_conn.commit()

    result = _decision_audit_html(db_conn)

    assert "WHAT CHANGES IT" in result
    assert "~53%" in result
    assert "View decision audit" in result
    assert "<details" in result
    assert "FINAL DECISION: ACT" in result
    assert "Tzolis -&gt; Tavernier" in result or "Tzolis -> Tavernier" in result
    assert "ROBUST" in result


def test_decision_audit_panel_is_wired_into_the_advanced_drawer(db_conn):
    """Decision Audit lives under Advanced (2026-08-27, frontend redesign -
    "historical audit belongs under Advanced, never the primary screen") -
    real end-to-end check that `generate_dashboard_html`'s Advanced/Decision
    Detail drawer actually includes it, not just the standalone
    `_decision_audit_html` unit above."""
    from fpl_agent.monitoring.dashboard import generate_dashboard_html
    from test_optimization_locked_squad import _seed_real_picks
    from test_dashboard import _seed

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_real_picks(db_conn)
    log_decision(db_conn, "decision_audit", "summary", _fake_audit_detail())
    db_conn.commit()

    result = generate_dashboard_html(db_conn)

    assert "View decision audit" in result
    assert 'id="advanced"' in result
