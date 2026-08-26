from types import SimpleNamespace

import fpl_agent.optimization.decision_analysis as da_mod
import fpl_agent.optimization.decision_engine as de_mod
import fpl_agent.optimization.transfers as transfers_mod
from fpl_agent.optimization.captaincy import CaptainOption
from fpl_agent.optimization.decision_analysis import analyze_captain_decision, analyze_transfer_decision
from fpl_agent.optimization.locked_squad import LockedSquadState
from fpl_agent.optimization.squad import PlayerCandidate, StartingXI
from fpl_agent.optimization.transfers import TransferCandidate


def _candidate(pid, web_name="P"):
    return PlayerCandidate(
        player_id=pid, web_name=web_name, position="MID", team_id=1, team_short="T1",
        price_tenths=50, xp=4.0, median=4.0, floor=2.0, ceiling=6.0, confidence="MEDIUM", expected_minutes=80.0,
    )


def _locked(squad_ids=(1, 2, 3), bank_tenths=10):
    xi = StartingXI(starting=[_candidate(pid) for pid in squad_ids], bench=[], captain=_candidate(squad_ids[0]), vice_captain=None)
    return LockedSquadState(
        source="synced_real", event=1, squad_ids=frozenset(squad_ids), xi=xi,
        bank_tenths=bank_tenths, squad_value_tenths=500, decision_id=None,
    )


def _tc(player_out_id, player_in_id, net_ev_3gw, player_out_name="OUT", player_in_name="IN"):
    return TransferCandidate(
        player_out_id=player_out_id, player_out_name=player_out_name, player_in_id=player_in_id, player_in_name=player_in_name,
        price_delta_tenths=0, ev_1gw=net_ev_3gw / 3, ev_3gw=net_ev_3gw, ev_5gw=net_ev_3gw * 5 / 3,
        net_ev_1gw=round(net_ev_3gw / 3, 2), net_ev_3gw=net_ev_3gw, net_ev_5gw=round(net_ev_3gw * 5 / 3, 2), uses_hit=False,
    )


def _stub_common(monkeypatch, transfer_map, robustness_verdict=None, qualitative_verdict="MODEL_WINS"):
    monkeypatch.setattr(da_mod, "_reference_event", lambda conn: 1)
    monkeypatch.setattr(
        transfers_mod, "_squad_gw_ev",
        lambda conn, squad_ids, event, cache: {1: 50.0, 2: 48.0, 3: 47.0, 4: 46.0, 5: 45.0}.get(event, 44.0),
    )
    monkeypatch.setattr(
        da_mod, "best_transfer_for_player",
        lambda conn, player_out_id, squad_ids, bank_tenths, is_hit, n_gw, top_n, from_event, cache: transfer_map.get(player_out_id, []),
    )
    import fpl_agent.models.robustness as robustness_mod
    import fpl_agent.models.decision_fusion as fusion_mod

    if robustness_verdict is not None:
        monkeypatch.setattr(
            robustness_mod, "compare_candidates",
            lambda conn, leader_id, challenger_id, from_event, n_trials: SimpleNamespace(verdict=robustness_verdict),
        )
    else:
        monkeypatch.setattr(robustness_mod, "compare_candidates", lambda *a, **k: None)
    monkeypatch.setattr(
        fusion_mod, "compare_transfer_views",
        lambda conn, squad_ids, bank_tenths: SimpleNamespace(verdict=qualitative_verdict, explanation="real qualitative reason"),
    )


def test_review_when_bank_is_unknown(db_conn):
    locked = _locked(bank_tenths=None)

    result = analyze_transfer_decision(db_conn, locked)

    assert result.decision_kind == "review"
    assert result.roll is None


def test_roll_reported_with_real_per_gw_and_horizon_totals(db_conn, monkeypatch):
    locked = _locked()
    _stub_common(monkeypatch, transfer_map={})

    result = analyze_transfer_decision(db_conn, locked)

    assert result.decision_kind == "roll"
    assert result.roll.per_gw[1] == 50.0
    assert result.roll.horizon_totals[1] == 50.0
    assert result.roll.horizon_totals[3] == 50.0 + 48.0 + 47.0
    assert result.roll.horizon_totals[5] == 50.0 + 48.0 + 47.0 + 46.0 + 45.0
    assert result.candidates == ()
    assert result.chosen is None


def test_transfer_recommended_when_best_candidate_clears_the_real_threshold(db_conn, monkeypatch):
    locked = _locked(squad_ids=(1, 2, 3))
    best = _tc(1, 99, 5.0, player_out_name="P1", player_in_name="P99")
    _stub_common(monkeypatch, transfer_map={1: [best]}, robustness_verdict="ROBUST")

    result = analyze_transfer_decision(db_conn, locked)

    assert result.decision_kind == "transfer"
    assert result.threshold_cleared is True
    assert result.chosen.candidate.player_in_name == "P99"
    assert result.expected_advantage_3gw == 5.0
    assert result.robustness == "ROBUST"


def test_roll_when_best_candidate_does_not_clear_the_threshold(db_conn, monkeypatch):
    locked = _locked(squad_ids=(1, 2, 3))
    weak = _tc(1, 99, 0.3, player_out_name="P1", player_in_name="P99")
    _stub_common(monkeypatch, transfer_map={1: [weak]})

    result = analyze_transfer_decision(db_conn, locked)

    assert result.decision_kind == "roll"
    assert result.threshold_cleared is False
    assert result.chosen is None
    assert result.expected_advantage_3gw == 0.3  # real best-found advantage, honestly reported even though it lost


def test_ranks_and_explains_rejected_alternatives(db_conn, monkeypatch):
    locked = _locked(squad_ids=(1, 2, 3))
    best = _tc(1, 99, 5.0, player_out_name="P1", player_in_name="Best")
    second = _tc(2, 98, 3.0, player_out_name="P2", player_in_name="Second")
    third = _tc(3, 97, 1.5, player_out_name="P3", player_in_name="Third")
    _stub_common(monkeypatch, transfer_map={1: [best], 2: [second], 3: [third]})

    result = analyze_transfer_decision(db_conn, locked)

    assert [o.candidate.player_in_name for o in result.candidates] == ["Best", "Second", "Third"]
    assert result.candidates[0].rejected_reason is None
    assert "2.0" in result.candidates[1].rejected_reason  # real 5.0-3.0 gap
    assert result.candidates[1].rank == 2


def test_qualitative_note_only_surfaces_on_a_real_disagreement(db_conn, monkeypatch):
    locked = _locked(squad_ids=(1, 2, 3))
    best = _tc(1, 99, 5.0)
    _stub_common(monkeypatch, transfer_map={1: [best]}, qualitative_verdict="QUALITATIVE_WINS")

    result = analyze_transfer_decision(db_conn, locked)

    assert result.qualitative_note == "real qualitative reason"


def test_future_ft_note_is_always_present_and_never_a_fabricated_number(db_conn, monkeypatch):
    locked = _locked()
    _stub_common(monkeypatch, transfer_map={})

    result = analyze_transfer_decision(db_conn, locked)

    assert "unquantified" in result.future_ft_note
    assert result.future_ft_note  # always present, even on a roll decision


def _captain_option(pid, median, web_name="P"):
    return CaptainOption(
        player_id=pid, web_name=web_name, position="MID", floor=2.0, median=median, ceiling=6.0,
        confidence="MEDIUM", expected_minutes=80.0, is_penalty_taker=False, opponent_short="OPP",
        is_home=True, selected_by_percent=10.0, effective_ownership_percent=None, eo_source="unavailable",
    )


def _stub_captain_common(monkeypatch, options, qualitative_verdict="MODEL_WINS", robustness_verdict=None):
    monkeypatch.setattr(da_mod, "_reference_event", lambda conn: 1)
    monkeypatch.setattr(da_mod, "evaluate_captaincy", lambda conn, squad_ids, event=None: options)
    monkeypatch.setattr(de_mod, "evaluate_captaincy", lambda conn, squad_ids: options)
    monkeypatch.setattr(
        "fpl_agent.models.lineup_state.resolve_lineup_state",
        lambda conn, player_id, event: SimpleNamespace(state="UNKNOWN"),
    )
    import fpl_agent.models.decision_fusion as fusion_mod
    import fpl_agent.models.robustness as robustness_mod

    monkeypatch.setattr(
        fusion_mod, "compare_captain_views",
        lambda conn, squad_ids: SimpleNamespace(verdict=qualitative_verdict, explanation="real qualitative reason"),
    )
    if robustness_verdict is not None:
        monkeypatch.setattr(
            robustness_mod, "compare_candidates",
            lambda conn, leader_id, challenger_id, from_event, n_trials: SimpleNamespace(verdict=robustness_verdict),
        )
    else:
        monkeypatch.setattr(robustness_mod, "compare_candidates", lambda *a, **k: None)


def test_captain_keep_reports_the_real_gap_below_threshold(db_conn, monkeypatch):
    locked = _locked(squad_ids=(1, 2, 3))
    options = [_captain_option(2, 5.4, "Best"), _captain_option(1, 5.0, "Cur")]
    _stub_captain_common(monkeypatch, options)

    result = analyze_captain_decision(db_conn, locked)

    assert result.decision_kind == "keep"
    assert "0.4" in result.reason
    assert result.options[0].rank == 1
    assert result.options[0].rejected_reason is None


def test_captain_change_recommended_and_ranks_real_alternatives(db_conn, monkeypatch):
    locked = _locked(squad_ids=(1, 2, 3))
    options = [_captain_option(2, 7.0, "Best"), _captain_option(1, 5.0, "Cur"), _captain_option(3, 4.0, "Third")]
    _stub_captain_common(monkeypatch, options, robustness_verdict="ROBUST")

    result = analyze_captain_decision(db_conn, locked)

    assert result.decision_kind == "change"
    assert result.suggested.player_id == 2
    assert result.delta == 2.0
    assert result.robustness == "ROBUST"
    assert [o.rank for o in result.options] == [1, 2, 3]
    assert result.options[1].rejected_reason is not None
    assert "2.0" in result.options[1].rejected_reason


def test_captain_qualitative_note_only_surfaces_on_a_real_disagreement(db_conn, monkeypatch):
    locked = _locked(squad_ids=(1, 2, 3))
    options = [_captain_option(1, 5.0, "Cur")]
    _stub_captain_common(monkeypatch, options, qualitative_verdict="UNDECIDED")

    result = analyze_captain_decision(db_conn, locked)

    assert result.qualitative_note == "real qualitative reason"
