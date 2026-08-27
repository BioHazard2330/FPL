from types import SimpleNamespace

import fpl_agent.monitoring.dashboard.legacy as dash_mod
from fpl_agent.database.decisions import log_decision
from fpl_agent.monitoring.dashboard.legacy import _compute_primary_verdict, _decision_comparison_html, _opportunity_board_html


def test_decision_comparison_absent_when_no_audit_cached(db_conn):
    assert _decision_comparison_html(db_conn) == ""


def test_decision_comparison_renders_roll_vs_transfer_vs_chip(db_conn):
    log_decision(
        db_conn, "decision_audit", "summary",
        {
            "action_audit": [
                {"label": "PLAY WILDCARD", "kind": "chip", "horizon_results": {"3": 245.8, "5": 403.8, "8": 642.1}},
                {"label": "Tzolis -> Tavernier", "kind": "transfer", "horizon_results": {"3": 207.3, "5": 376.5, "8": 616.2}},
                {"label": "ROLL", "kind": "roll", "horizon_results": {"3": 202.7, "5": 371.9, "8": 611.5}},
            ],
        },
    )
    db_conn.commit()

    result = _decision_comparison_html(db_conn)

    assert "ROLL" in result and "BEST TRANSFER" in result and "BEST CHIP" in result
    assert "+642.1" in result
    assert "Tzolis -&gt; Tavernier" in result or "Tzolis -> Tavernier" in result
    assert "diagnostic context, not a second recommendation" in result
    assert "&amp;mdash;" not in result  # no double-escaped entities


def test_decision_comparison_absent_with_fewer_than_two_real_candidates(db_conn):
    log_decision(db_conn, "decision_audit", "summary", {"action_audit": [{"label": "ROLL", "kind": "roll", "horizon_results": {"8": 500.0}}]})
    db_conn.commit()

    assert _decision_comparison_html(db_conn) == ""


def test_opportunity_board_empty_state_when_nothing_clears_the_bar(db_conn, monkeypatch):
    monkeypatch.setattr(dash_mod, "find_breakouts", lambda conn: [])
    monkeypatch.setattr(dash_mod, "find_traps", lambda conn: [])

    result = _opportunity_board_html(db_conn, set())

    assert "No real league-wide opportunities" in result


def _breakout(player_id=1, web_name="Mendy", position="DEF", value_ratio=1.2, ownership=2.9, reasons=None):
    return SimpleNamespace(
        player_id=player_id, web_name=web_name, position=position, value_ratio=value_ratio,
        ownership_percent=ownership, reasons=reasons or ["real rising value"],
    )


def _trap(player_id=2, web_name="O'Reilly", position="DEF", ownership=21.1, eo_source="raw", reasons=None):
    return SimpleNamespace(
        player_id=player_id, web_name=web_name, position=position, ownership_percent=ownership,
        eo_source=eo_source, reasons=reasons or ["real deteriorating case"],
    )


def test_opportunity_board_renders_a_breakout_card_and_excludes_squad_members(db_conn, monkeypatch):
    monkeypatch.setattr(dash_mod, "find_breakouts", lambda conn: [_breakout(player_id=1), _breakout(player_id=2, web_name="Already Owned")])
    monkeypatch.setattr(dash_mod, "find_traps", lambda conn: [])

    result = _opportunity_board_html(db_conn, {2})  # player 2 already in squad

    assert "Mendy" in result
    assert "Already Owned" not in result
    assert "opp-card-breakout" in result
    assert "1.20 xP/£m" in result  # real "£" character, never a double-escaped entity


def test_opportunity_board_renders_a_trap_card_with_real_reasons(db_conn, monkeypatch):
    monkeypatch.setattr(dash_mod, "find_breakouts", lambda conn: [])
    monkeypatch.setattr(dash_mod, "find_traps", lambda conn: [_trap()])

    result = _opportunity_board_html(db_conn, set())

    assert "opp-card-trap" in result
    assert "O&#x27;Reilly" in result or "O'Reilly" in result
    assert "real deteriorating case" in result
    assert "&amp;middot;" not in result  # no double-escaped entities (real bug found live in this pass)


def _ta(decision_kind="roll", chosen=False):
    return SimpleNamespace(decision_kind=decision_kind, chosen=None, reason="no real transfer candidate exists")


def test_compute_primary_verdict_falls_back_to_roll_with_no_cached_strategic_plan(db_conn):
    verdict = _compute_primary_verdict(db_conn, _ta())

    assert verdict.verdict == "ROLL"
    assert verdict.current_rec is None


def test_compute_primary_verdict_reads_the_real_cached_current_recommendation(db_conn):
    from fpl_agent.database.decisions import log_decision

    log_decision(
        db_conn, "strategic_plan", "PLAY WILDCARD wins",
        {
            "horizon_gw": 8,
            "current_recommendation": {
                "label": "PLAY WILDCARD", "verdict": "ACT", "action_kind": "chip",
                "path_total": 642.12, "reason": "PLAY WILDCARD has the best real full-horizon future",
                "starting_action_options": [],
            },
        },
    )
    db_conn.commit()

    verdict = _compute_primary_verdict(db_conn, _ta())

    assert verdict.verdict == "CHIP"
    assert verdict.action_label == "PLAY WILDCARD"
    assert "642.12" in verdict.ev_suffix or "642.1" in verdict.ev_suffix
