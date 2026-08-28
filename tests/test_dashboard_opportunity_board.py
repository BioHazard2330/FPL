from types import SimpleNamespace

import fpl_agent.monitoring.dashboard.opportunity as opportunity_mod
from fpl_agent.database.decisions import log_decision
from fpl_agent.monitoring.dashboard.legacy import _compute_primary_verdict, _decision_comparison_html
from fpl_agent.monitoring.dashboard.opportunity import render_opportunity_workspace


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
    monkeypatch.setattr(opportunity_mod, "find_breakouts", lambda conn: [])
    monkeypatch.setattr(opportunity_mod, "find_traps", lambda conn: [])

    result = render_opportunity_workspace(db_conn, set())

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
    monkeypatch.setattr(opportunity_mod, "find_breakouts", lambda conn: [_breakout(player_id=1), _breakout(player_id=2, web_name="Already Owned")])
    monkeypatch.setattr(opportunity_mod, "find_traps", lambda conn: [])

    result = render_opportunity_workspace(db_conn, {2})  # player 2 already in squad

    assert "Mendy" in result
    assert "Already Owned" not in result
    assert "opp-card-breakout" in result
    assert "1.20 xP/£m" in result  # real "£" character, never a double-escaped entity


def _fake_transfer_option(player_out_name, player_in_id):
    candidate = SimpleNamespace(player_out_name=player_out_name, player_in_id=player_in_id)
    return SimpleNamespace(candidate=candidate)


def test_opportunity_board_shows_real_squad_impact_when_a_card_is_a_real_transfer_candidate(db_conn, monkeypatch):
    """fpl.page-parity pass: MY SQUAD IMPACT reuses the SAME real
    `analyze_transfer_decision` candidates already computed - never a
    second, invented replacement guess."""
    monkeypatch.setattr(opportunity_mod, "find_breakouts", lambda conn: [_breakout(player_id=1)])
    monkeypatch.setattr(opportunity_mod, "find_traps", lambda conn: [])
    ta = SimpleNamespace(candidates=[_fake_transfer_option("Tzolis", 1)])

    result = render_opportunity_workspace(db_conn, set(), ta=ta)

    assert "opp-card-squad-impact" in result
    assert "Would replace" in result and "Tzolis" in result


def test_opportunity_board_no_squad_impact_line_without_a_real_transfer_match(db_conn, monkeypatch):
    monkeypatch.setattr(opportunity_mod, "find_breakouts", lambda conn: [_breakout(player_id=1)])
    monkeypatch.setattr(opportunity_mod, "find_traps", lambda conn: [])
    ta = SimpleNamespace(candidates=[_fake_transfer_option("Someone", player_in_id=999)])  # different player

    result = render_opportunity_workspace(db_conn, set(), ta=ta)

    assert "opp-card-squad-impact" not in result


def test_opportunity_board_renders_a_trap_card_with_real_reasons(db_conn, monkeypatch):
    monkeypatch.setattr(opportunity_mod, "find_breakouts", lambda conn: [])
    monkeypatch.setattr(opportunity_mod, "find_traps", lambda conn: [_trap()])

    result = render_opportunity_workspace(db_conn, set())

    assert "opp-card-trap" in result
    assert "O&#x27;Reilly" in result or "O'Reilly" in result
    assert "real deteriorating case" in result
    assert "&amp;middot;" not in result  # no double-escaped entities (real bug found live in this pass)


def test_opportunity_board_omits_considered_flag_when_no_strategic_plan_run(db_conn, monkeypatch):
    """`considered_ids=None` (no strategic plan run this session) must not
    render any considered/not-considered claim - honest omission, never a
    guessed default."""
    monkeypatch.setattr(opportunity_mod, "find_breakouts", lambda conn: [_breakout(player_id=1)])
    monkeypatch.setattr(opportunity_mod, "find_traps", lambda conn: [])

    result = render_opportunity_workspace(db_conn, set())

    assert "opp-card-considered" not in result


def test_opportunity_board_marks_a_player_considered_by_the_optimizer(db_conn, monkeypatch):
    monkeypatch.setattr(opportunity_mod, "find_breakouts", lambda conn: [_breakout(player_id=1)])
    monkeypatch.setattr(opportunity_mod, "find_traps", lambda conn: [])

    result = render_opportunity_workspace(db_conn, set(), considered_ids={1, 99})

    assert "Considered by optimizer" in result
    assert "opp-card-considered-yes" in result
    assert "Not evaluated by the optimizer" not in result


def test_opportunity_board_marks_a_player_not_considered_by_the_optimizer(db_conn, monkeypatch):
    monkeypatch.setattr(opportunity_mod, "find_breakouts", lambda conn: [_breakout(player_id=1)])
    monkeypatch.setattr(opportunity_mod, "find_traps", lambda conn: [])

    result = render_opportunity_workspace(db_conn, set(), considered_ids={99})

    assert "Not evaluated by the optimizer" in result
    assert "opp-card-considered-no" in result
    assert "Considered by optimizer" not in result


def test_opportunity_board_value_category_excludes_squad_members(db_conn):
    """Real live-screenshot QA finding (2026-08-29): a squad member showing
    up in the Value category read as a nonsensical "buy this" suggestion for
    a player the user already owns - Breakout already excluded squad
    members, Value didn't. Real, minimal fixture: two price-rise rows, one
    for a squad member (must be excluded) and one for a non-squad player
    (must still appear)."""
    now = "2026-08-01T00:00:00Z"
    db_conn.execute(f"INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'T1','T1','{now}')")
    db_conn.execute(
        f"INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, squad_min_play, "
        f"squad_max_play, squad_select, updated_at) VALUES (1,'Defender','DEF','Defenders',3,5,5,'{now}')"
    )
    for pid, name in ((1, "SquadPlayer"), (2, "FreeAgent")):
        db_conn.execute(
            f"INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
            f"VALUES ({pid},{pid},'{name}',1,1,'a',0,'{now}')"
        )
        db_conn.execute(
            f"INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) "
            f"VALUES ({pid}, 50, '2026-07-01T00:00:00Z', '{now}')"
        )
        db_conn.execute(
            f"INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) "
            f"VALUES ({pid}, 55, '{now}', NULL)"
        )
    db_conn.commit()

    result = render_opportunity_workspace(db_conn, squad_ids={1})

    assert "FreeAgent" in result
    assert "SquadPlayer" not in result


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
