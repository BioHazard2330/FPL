import fpl_agent.optimization.strategic_planner as sp_mod
from fpl_agent.optimization.strategic_planner import build_strategic_plan
from fpl_agent.optimization.transfers import TransferSequence, TransferSequenceStep


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
        lambda conn, squad_ids, ft, bank, horizon_gw, beam_width: [_seq([_swap_step(2)], 10.0 * horizon_gw)],
    )

    plan = build_strategic_plan(None, [1, 2, 3], free_transfers=1, bank_tenths=0, horizon_gw=8)

    assert plan.immediate_vs_strategic_differ is False
    assert "consistent across every horizon" in plan.note


def test_immediate_and_strategic_optimum_disagree_is_detected(monkeypatch):
    def fake_search(conn, squad_ids, ft, bank, horizon_gw, beam_width):
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
