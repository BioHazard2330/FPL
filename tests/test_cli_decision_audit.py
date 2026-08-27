import json
from types import SimpleNamespace

from click.testing import CliRunner

import fpl_agent.optimization.adversarial_audit as aa_mod
from fpl_agent.cli.main import cli
from test_dashboard import _seed
from test_optimization_locked_squad import _seed_real_picks


def _fake_audit():
    causal = [SimpleNamespace(label="STARTING ACTION", detail="ROLL")]
    action_row = SimpleNamespace(
        label="ROLL", kind="roll", horizon_results={3: 10.0}, opportunity_cost="n/a - this is the winning action",
        confidence=None, robustness=None, main_reason_rejected=None,
    )
    player_audit = SimpleNamespace(
        player_id=1, web_name="Best", expected_minutes=85.0, p_zero=0.1, p_partial=0.1, p_full=0.8,
        total_xp_1gw=6.0, components={}, data_confidence="MEDIUM", minutes_confidence="MEDIUM",
        overall_confidence="MEDIUM", understat_matches_played=2.0, minutes_basis="current_season_only",
        rotation_risk=None, cross_league_prior_used=False, evidence_reasons=(), current_role=None,
        current_tactical_signal=None, current_fpl_outlook=None, persistent_trends=[], ownership_percent=5.0,
        ownership_source="sampled", price_direction="STABLE", decision_contribution="squad member",
    )
    mf = SimpleNamespace(player_id=1, web_name="Best", model_view="6.0 xP", football_view="none",
                          agreement="NO_FOOTBALL_SIGNAL", decision_impact="none")
    stress = SimpleNamespace(dimension="MINUTES", magnitude=0.15, baseline_delta=0.0, stressed_delta=0.0,
                              decision_flips=False, note="no real chosen swap to stress-test")
    falsifier = SimpleNamespace(description="no real transfer candidate to falsify", threshold_note="n/a")
    league = SimpleNamespace(candidate_pool_scope="scope note", breakout_count=0, differential_count=0,
                              trap_count=0, chosen_in_is_trap=False, top_breakouts=[], top_differentials=[])
    cold = SimpleNamespace(player_id=1, web_name="Best", understat_matches_played=0.0, data_confidence="LOW",
                            minutes_basis="no_data_available", cross_league_prior_used=False, prior_is_stale=False,
                            note="pure positional-average fallback")
    qual = SimpleNamespace(player_id=1, web_name="Best", observed="obs", inferred="inf", fpl_implication="POSITIVE",
                            projection_component_affected="goals", decision_impact="none")
    scorecard = SimpleNamespace(
        data_quality="MEDIUM", model_quality="ROBUST", football_evidence="NO DISAGREEMENT",
        market_evidence="NO TRAP FLAG", decision_robustness="ROBUST", counterfactual_stability="ROBUST",
        information_sufficiency="not assessed", final_decision="ROLL", confidence="MEDIUM",
        why_trust=["real evidence confidence is MEDIUM"], why_might_not_trust=["no specific real weakness identified"],
        what_would_change_my_mind=["no real numeric falsifier could be derived"],
    )
    return SimpleNamespace(
        event=1, causal_chain=causal, player_audits=[player_audit], model_football=[mf], stress_tests=[stress],
        falsifiers=[falsifier], action_audit=[action_row], league_wide=league, cold_start=[cold],
        qualitative_chain=[qual], external_context_notes=["note"], scorecard=scorecard, cross_check_note=None,
    )


def test_decision_audit_cmd_logs_and_prints_the_scorecard(db_conn, monkeypatch):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_real_picks(db_conn)
    monkeypatch.setattr(aa_mod, "run_adversarial_audit", lambda *a, **k: _fake_audit())

    result = CliRunner().invoke(cli, ["decision-audit", "--horizons", "3"])

    assert result.exit_code == 0, result.output
    assert "FINAL DECISION: ROLL" in result.output
    assert "WHY I TRUST THIS" in result.output
    assert "WHAT WOULD CHANGE MY MIND" in result.output

    row = db_conn.execute(
        "SELECT summary, detail FROM decisions WHERE decision_type='decision_audit' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert "ROLL" in row["summary"]
    detail = json.loads(row["detail"])
    assert detail["scorecard"]["final_decision"] == "ROLL"
    assert detail["action_audit"][0]["label"] == "ROLL"


def test_decision_audit_cmd_requires_a_locked_squad(db_conn, monkeypatch):
    result = CliRunner().invoke(cli, ["decision-audit"])

    assert result.exit_code != 0
    assert "no real locked squad found" in result.output


def test_decision_audit_cmd_prints_a_warning_when_it_disagrees_with_strategic_plan(db_conn, monkeypatch):
    """Real regression test for the actual disagreement this audit's own
    first live production run surfaced (2026-08-27): at a narrow beam width
    it found PLAY WILDCARD winning while the SAME-DAY cached `fpl
    strategic-plan` run (wider, project-standard beam width) found ROLL
    winning - a real chip-full-rebuild-vs-beam-limited-search artifact, not
    a genuine new insight. The CLI must surface this loudly, never silently
    prefer its own narrower answer."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_real_picks(db_conn)
    audit = _fake_audit()
    audit.cross_check_note = "DISAGREES with the cached `fpl strategic-plan` result: that run found ROLL wins"
    monkeypatch.setattr(aa_mod, "run_adversarial_audit", lambda *a, **k: audit)

    result = CliRunner().invoke(cli, ["decision-audit", "--horizons", "3"])

    assert result.exit_code == 0, result.output
    assert "METHODOLOGY CROSS-CHECK WARNING" in result.output
    assert "DISAGREES with the cached" in result.output

    row = db_conn.execute(
        "SELECT detail FROM decisions WHERE decision_type='decision_audit' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    detail = json.loads(row["detail"])
    assert detail["cross_check_note"] is not None
