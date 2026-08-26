from types import SimpleNamespace

import fpl_agent.optimization.decision_engine as de_mod
from fpl_agent.optimization.captaincy import CaptainOption
from fpl_agent.optimization.decision_engine import evaluate_locked_squad
from fpl_agent.optimization.locked_squad import LockedSquadState
from fpl_agent.optimization.squad import PlayerCandidate, StartingXI
from fpl_agent.optimization.transfers import TransferCandidate


def _candidate(pid, web_name="P", position="MID"):
    return PlayerCandidate(
        player_id=pid, web_name=web_name, position=position, team_id=1, team_short="T1",
        price_tenths=50, xp=4.0, median=4.0, floor=2.0, ceiling=6.0, confidence="MEDIUM", expected_minutes=80.0,
    )


def _captain_option(pid, median, web_name="P"):
    return CaptainOption(
        player_id=pid, web_name=web_name, position="MID", floor=2.0, median=median, ceiling=6.0,
        confidence="MEDIUM", expected_minutes=80.0, is_penalty_taker=False, opponent_short="OPP",
        is_home=True, selected_by_percent=10.0, effective_ownership_percent=None, eo_source="unavailable",
    )


def _locked(captain_id=1, squad_ids=(1, 2, 3), bank_tenths=10):
    xi = StartingXI(
        starting=[_candidate(pid) for pid in squad_ids], bench=[],
        captain=_candidate(captain_id), vice_captain=None,
    )
    return LockedSquadState(
        source="synced_real", event=1, squad_ids=frozenset(squad_ids), xi=xi,
        bank_tenths=bank_tenths, squad_value_tenths=500, decision_id=None,
    )


def _stub_common(monkeypatch, captain_options, transfer_map):
    monkeypatch.setattr(de_mod, "evaluate_captaincy", lambda conn, squad_ids: captain_options)
    monkeypatch.setattr(
        de_mod, "best_transfer_for_player",
        lambda conn, player_out_id, squad_ids, bank_tenths, is_hit, n_gw, top_n: transfer_map.get(player_out_id, []),
    )
    monkeypatch.setattr("fpl_agent.models.availability.list_availability", lambda conn, unavailable_only=True: [])
    monkeypatch.setattr("fpl_agent.models.team_news_risk.flag_squad_rotation_risk", lambda conn, squad_ids: [])


def test_keep_captain_when_already_the_best_real_option(db_conn, monkeypatch):
    locked = _locked(captain_id=1)
    _stub_common(monkeypatch, [_captain_option(1, 5.0), _captain_option(2, 3.0)], {})

    decision = evaluate_locked_squad(db_conn, locked)

    assert decision.captain_action.kind == "keep"
    assert decision.captain_action.delta == 0.0


def test_keep_captain_when_delta_is_below_the_real_materiality_threshold(db_conn, monkeypatch):
    locked = _locked(captain_id=1)
    _stub_common(monkeypatch, [_captain_option(2, 5.2), _captain_option(1, 5.0)], {})

    decision = evaluate_locked_squad(db_conn, locked)

    assert decision.captain_action.kind == "keep"


def test_captain_change_recommended_when_delta_clears_the_threshold(db_conn, monkeypatch):
    locked = _locked(captain_id=1)
    _stub_common(monkeypatch, [_captain_option(2, 7.0), _captain_option(1, 5.0)], {})

    decision = evaluate_locked_squad(db_conn, locked)

    assert decision.captain_action.kind == "change"
    assert decision.captain_action.suggested.player_id == 2
    assert decision.captain_action.delta == 2.0


def test_captain_unavailable_when_no_real_options_exist(db_conn, monkeypatch):
    locked = _locked(captain_id=1)
    _stub_common(monkeypatch, [], {})

    decision = evaluate_locked_squad(db_conn, locked)

    assert decision.captain_action.kind == "unavailable"


def test_no_transfer_action_without_a_known_real_bank(db_conn, monkeypatch):
    """locked_decision source (pre-sync) has bank_tenths=None - never
    fabricate a budget to evaluate transfers against."""
    locked = _locked(captain_id=1, bank_tenths=None)
    _stub_common(monkeypatch, [_captain_option(1, 5.0)], {})

    decision = evaluate_locked_squad(db_conn, locked)

    assert decision.transfer_action.kind == "keep"
    assert decision.transfer_action.candidate is None


def test_keep_when_no_transfer_clears_the_real_materiality_threshold(db_conn, monkeypatch):
    weak = TransferCandidate(
        player_out_id=1, player_out_name="P1", player_in_id=99, player_in_name="P99",
        price_delta_tenths=0, ev_1gw=0.2, ev_3gw=0.2, ev_5gw=0.2,
        net_ev_1gw=0.2, net_ev_3gw=0.2, net_ev_5gw=0.2, uses_hit=False,
    )
    locked = _locked(captain_id=1, squad_ids=(1, 2, 3))
    _stub_common(monkeypatch, [_captain_option(1, 5.0)], {1: [weak]})

    decision = evaluate_locked_squad(db_conn, locked)

    assert decision.transfer_action.kind == "keep"


# --- Real hard override: confirmed-benched/out captain is never "keep" (2026-08-22) ---

def _stub_lineup_state(monkeypatch, states: dict):
    import fpl_agent.models.lineup_state as ls_mod
    from fpl_agent.models.lineup_state import LineupState

    def fake_resolve(conn, player_id, event):
        state = states.get(player_id, "UNKNOWN")
        return LineupState(player_id, state, None, "test")

    monkeypatch.setattr(ls_mod, "resolve_lineup_state", fake_resolve)


def test_captain_forced_to_change_when_confirmed_benched_even_if_still_the_best_median(db_conn, monkeypatch):
    """A real, decisive override: the captain's own median might still look
    best (the projection model hasn't caught up to a last-minute confirmed
    exclusion), but a confirmed-benched captain is never "keep"."""
    locked = _locked(captain_id=1)
    _stub_common(monkeypatch, [_captain_option(1, 5.0), _captain_option(2, 3.0)], {})
    _stub_lineup_state(monkeypatch, {1: "CONFIRMED_BENCHED"})

    decision = evaluate_locked_squad(db_conn, locked)

    assert decision.captain_action.kind == "change"
    assert decision.captain_action.suggested.player_id == 2  # the best real alternative, not the excluded captain


def test_captain_forced_to_change_when_out_unavailable(db_conn, monkeypatch):
    locked = _locked(captain_id=1)
    _stub_common(monkeypatch, [_captain_option(2, 7.0), _captain_option(1, 5.0)], {})
    _stub_lineup_state(monkeypatch, {1: "OUT_UNAVAILABLE"})

    decision = evaluate_locked_squad(db_conn, locked)

    assert decision.captain_action.kind == "change"
    assert decision.captain_action.suggested.player_id == 2


def test_captain_kept_when_predicted_start_not_confirmed_benched(db_conn, monkeypatch):
    """The override only fires on a real CONFIRMED_BENCHED/OUT_UNAVAILABLE
    state - a merely predicted or unconfirmed state must not trigger it."""
    locked = _locked(captain_id=1)
    _stub_common(monkeypatch, [_captain_option(1, 5.0), _captain_option(2, 4.9)], {})
    _stub_lineup_state(monkeypatch, {1: "PREDICTED_START"})

    decision = evaluate_locked_squad(db_conn, locked)

    assert decision.captain_action.kind == "keep"


def test_transfer_recommended_when_a_real_candidate_clears_the_threshold(db_conn, monkeypatch):
    strong = TransferCandidate(
        player_out_id=2, player_out_name="P2", player_in_id=99, player_in_name="P99",
        price_delta_tenths=0, ev_1gw=1.5, ev_3gw=2.5, ev_5gw=3.0,
        net_ev_1gw=1.5, net_ev_3gw=2.5, net_ev_5gw=3.0, uses_hit=False,
    )
    locked = _locked(captain_id=1, squad_ids=(1, 2, 3))
    _stub_common(monkeypatch, [_captain_option(1, 5.0)], {2: [strong]})

    decision = evaluate_locked_squad(db_conn, locked)

    assert decision.transfer_action.kind == "transfer"
    assert decision.transfer_action.candidate.player_in_name == "P99"


def test_transfer_robustness_is_attached_when_a_real_comparison_succeeds(db_conn, monkeypatch):
    """P1 'transfer robustness comparison' - wired the same way captain's
    own robustness label is, using the transfer candidate's real
    player_out/player_in ids."""
    strong = TransferCandidate(
        player_out_id=2, player_out_name="P2", player_in_id=99, player_in_name="P99",
        price_delta_tenths=0, ev_1gw=1.5, ev_3gw=2.5, ev_5gw=3.0,
        net_ev_1gw=1.5, net_ev_3gw=2.5, net_ev_5gw=3.0, uses_hit=False,
    )
    locked = _locked(captain_id=1, squad_ids=(1, 2, 3))
    _stub_common(monkeypatch, [_captain_option(1, 5.0)], {2: [strong]})
    monkeypatch.setattr(
        "fpl_agent.models.robustness.compare_candidates",
        lambda conn, leader_id, challenger_id, from_event, n_trials: SimpleNamespace(verdict="FRAGILE"),
    )

    decision = evaluate_locked_squad(db_conn, locked)

    assert decision.transfer_action.robustness == "FRAGILE"


def test_transfer_robustness_is_none_for_a_keep_verdict(db_conn, monkeypatch):
    locked = _locked(captain_id=1, squad_ids=(1, 2, 3))
    _stub_common(monkeypatch, [_captain_option(1, 5.0)], {})

    decision = evaluate_locked_squad(db_conn, locked)

    assert decision.transfer_action.kind == "keep"
    assert decision.transfer_action.robustness is None
