from types import SimpleNamespace

import fpl_agent.optimization.strategic_planner as sp_mod
from fpl_agent.database.decisions import log_decision
from fpl_agent.optimization.strategic_planner import (
    build_strategic_plan,
    latest_strategic_plan_with_recommendation,
    strategic_plan_decisions_with_recommendation,
    synthesize_current_recommendation,
)
from fpl_agent.optimization.transfers import StartingActionOption, TransferSequence, TransferSequenceStep


def _seq(steps, total_net_ev, final_ft=1, final_bank=0):
    return TransferSequence(
        steps=tuple(steps), final_squad_ids=(1, 2, 3), final_free_transfers=final_ft,
        final_bank_tenths=final_bank, total_net_ev=total_net_ev, tiebreak_adjustment=0.0,
    )


def _roll_step(event):
    return TransferSequenceStep(event=event, player_out_id=None, player_out_name=None, player_in_id=None, player_in_name=None, uses_hit=False)


def _swap_step(event, out_id=1, out_name="A", in_id=99, in_name="B", hit=False):
    return TransferSequenceStep(event=event, player_out_id=out_id, player_out_name=out_name, player_in_id=in_id, player_in_name=in_name, uses_hit=hit)


def test_returns_the_real_top_paths_at_the_requested_horizon(monkeypatch):
    paths = [_seq([_swap_step(2)], 10.0), _seq([_swap_step(2)], 9.5)]
    monkeypatch.setattr(sp_mod, "search_transfer_sequences", lambda *a, **k: paths)

    plan = build_strategic_plan(None, [1, 2, 3], free_transfers=1, bank_tenths=0, horizon_gw=8)

    assert plan.paths == tuple(paths)
    assert plan.best is paths[0]


def test_immediate_and_strategic_optimum_agree_reports_no_difference(monkeypatch):
    monkeypatch.setattr(
        sp_mod, "search_transfer_sequences",
        lambda conn, squad_ids, ft, bank, horizon_gw, beam_width, **kw: [_seq([_swap_step(2)], 10.0 * horizon_gw)],
    )

    plan = build_strategic_plan(None, [1, 2, 3], free_transfers=1, bank_tenths=0, horizon_gw=8)

    assert plan.immediate_vs_strategic_differ is False
    assert "consistent across every horizon" in plan.note


def test_immediate_and_strategic_optimum_disagree_is_detected(monkeypatch):
    def fake_search(conn, squad_ids, ft, bank, horizon_gw, beam_width, **kw):
        if horizon_gw == 8:
            return [_seq([_swap_step(2, out_name="Long", in_name="Term")], 500.0)]
        return [_seq([_swap_step(2, out_name="Short", in_name="Fix")], 10.0)]

    monkeypatch.setattr(sp_mod, "search_transfer_sequences", fake_search)

    plan = build_strategic_plan(None, [1, 2, 3], free_transfers=1, bank_tenths=0, horizon_gw=8)

    assert plan.immediate_vs_strategic_differ is True
    assert "IMMEDIATE optimum" in plan.note
    assert "STRATEGIC optimum" in plan.note


def test_roll_opening_action_is_labeled_correctly(monkeypatch):
    monkeypatch.setattr(sp_mod, "search_transfer_sequences", lambda *a, **k: [_seq([_roll_step(2)], 5.0)])

    plan = build_strategic_plan(None, [1, 2, 3], free_transfers=1, bank_tenths=0, horizon_gw=1)

    assert plan.horizon_comparison[0].opening_action == "ROLL"


def test_handles_no_real_legal_path_found(monkeypatch):
    monkeypatch.setattr(sp_mod, "search_transfer_sequences", lambda *a, **k: [])

    plan = build_strategic_plan(None, [1, 2, 3], free_transfers=1, bank_tenths=0, horizon_gw=8)

    assert plan.best is None
    assert "no real legal path" in plan.note


def _option(label, kind, path_total, out_id=None, in_id=None):
    return StartingActionOption(
        label=label, kind=kind, player_out_id=out_id, player_out_name=None,
        player_in_id=in_id, player_in_name=None, chip_name=None, uses_hit=False,
        path_total=path_total, best_continuation=None,
    )


def test_synthesize_current_recommendation_acts_on_the_best_full_horizon_option(monkeypatch):
    """Real P0 "fix the decision hierarchy" behaviour: the winning
    full-horizon option is the recommendation, even when it differs from the
    immediate 1-GW pick - the strategic path_total already accounts for this
    GW too, so it takes priority rather than needing the user to reconcile."""
    options = [
        _option("A -> B", "transfer", 50.0, out_id=1, in_id=2),
        _option("ROLL", "roll", 40.0),
    ]
    monkeypatch.setattr(sp_mod, "compare_starting_actions", lambda *a, **k: options)
    monkeypatch.setattr(sp_mod, "_safe_confidence", lambda conn, pid: SimpleNamespace(overall="HIGH"))

    rec = synthesize_current_recommendation(
        None, [1, 2, 3], free_transfers=1, bank_tenths=0, immediate_optimum_label="ROLL",
    )

    assert rec.verdict == "ACT"
    assert rec.label == "A -> B"
    assert rec.action_kind == "transfer"
    assert rec.path_total == 50.0
    assert rec.immediate_vs_strategic_differ is True
    assert rec.evidence_confidence == "HIGH"


def test_synthesize_current_recommendation_downgrades_to_review_on_weak_evidence(monkeypatch):
    """A real EV lead is not the same claim as well-evidenced enough to act
    on - same REVIEW gate decision_analysis.py's single-swap recommendation
    already applies, now also applied to the strategic winner."""
    options = [_option("A -> B", "transfer", 50.0, out_id=1, in_id=2)]
    monkeypatch.setattr(sp_mod, "compare_starting_actions", lambda *a, **k: options)
    monkeypatch.setattr(sp_mod, "_safe_confidence", lambda conn, pid: SimpleNamespace(overall="LOW"))

    rec = synthesize_current_recommendation(None, [1, 2, 3], free_transfers=1, bank_tenths=0)

    assert rec.verdict == "REVIEW"
    assert rec.evidence_confidence == "LOW"
    assert "A -> B" in rec.reason


def test_synthesize_current_recommendation_never_gates_roll_or_chip(monkeypatch):
    """ROLL/chip actions have no specific player-pair projection to distrust -
    the evidence gate must never fire for them."""
    options = [_option("PLAY WILDCARD", "chip", 80.0)]
    monkeypatch.setattr(sp_mod, "compare_starting_actions", lambda *a, **k: options)

    def _boom(conn, pid):
        raise AssertionError("should never be called for a chip/roll action")

    monkeypatch.setattr(sp_mod, "_safe_confidence", _boom)

    rec = synthesize_current_recommendation(None, [1, 2, 3], free_transfers=1, bank_tenths=0)

    assert rec.verdict == "ACT"
    assert rec.evidence_confidence is None


def test_synthesize_current_recommendation_prefers_a_known_wider_beam_result(monkeypatch):
    """A narrower `continuation_beam_width` sub-search can understate an
    action's true best future relative to the caller's own already-computed
    wider main beam search - `known_paths` must let the wider, more reliable
    number win rather than silently trusting whichever number happened to be
    computed by the narrower search."""
    options = [
        _option("ROLL", "roll", 100.0),  # understated by the narrow continuation search
        _option("A -> B", "transfer", 105.0, out_id=1, in_id=2),
    ]
    monkeypatch.setattr(sp_mod, "compare_starting_actions", lambda *a, **k: options)
    monkeypatch.setattr(sp_mod, "_safe_confidence", lambda conn, pid: SimpleNamespace(overall="HIGH"))

    known_paths = (_seq([_roll_step(2)], 120.0),)  # the real, wider main search found ROLL is actually worth 120.0

    rec = synthesize_current_recommendation(None, [1, 2, 3], free_transfers=1, bank_tenths=0, known_paths=known_paths)

    assert rec.label == "ROLL"
    assert rec.path_total == 120.0


def test_synthesize_current_recommendation_handles_no_options(monkeypatch):
    monkeypatch.setattr(sp_mod, "compare_starting_actions", lambda *a, **k: [])

    rec = synthesize_current_recommendation(None, [1, 2, 3], free_transfers=1, bank_tenths=0)

    assert rec.verdict == "REVIEW"
    assert rec.label == "ROLL"


def _log_plan(conn, current_recommendation=..., **extra_detail):
    """`...` (the default) omits the key entirely (real old-schema row);
    pass `None` explicitly to simulate a real `--no-current-action` run."""
    detail = dict(extra_detail)
    if current_recommendation is not ...:
        detail["current_recommendation"] = current_recommendation
    return log_decision(conn, "strategic_plan", summary="test", detail=detail)


def test_latest_strategic_plan_with_recommendation_skips_a_no_current_action_run(db_conn):
    """Real production bug (2026-08-29): a `--no-current-action` search-
    diagnostic run can become the latest `strategic_plan` decision without
    ever computing `current_recommendation` - every consumer of "the
    authoritative current plan" must skip it, not surface a null decision."""
    _log_plan(db_conn, current_recommendation={"label": "ROLL", "verdict": "ACT", "path_total": 100.0})
    _log_plan(db_conn, current_recommendation=None)  # the diagnostic run, logged AFTER the real one

    latest = latest_strategic_plan_with_recommendation(db_conn)

    assert latest is not None
    assert latest.detail["current_recommendation"]["label"] == "ROLL"


def test_latest_strategic_plan_with_recommendation_none_when_nothing_complete_exists(db_conn):
    _log_plan(db_conn, current_recommendation=None)
    _log_plan(db_conn)  # old-schema row, key entirely absent

    assert latest_strategic_plan_with_recommendation(db_conn) is None


def test_strategic_plan_decisions_with_recommendation_returns_the_real_two_most_recent_complete_ones(db_conn):
    _log_plan(db_conn, current_recommendation={"label": "ROLL", "verdict": "ACT", "path_total": 1.0})
    _log_plan(db_conn, current_recommendation=None)  # diagnostic run sandwiched in between
    _log_plan(db_conn, current_recommendation={"label": "PLAY WILDCARD", "verdict": "ACT", "path_total": 2.0})

    rows = strategic_plan_decisions_with_recommendation(db_conn, limit=2)

    assert [r.detail["current_recommendation"]["label"] for r in rows] == ["PLAY WILDCARD", "ROLL"]
