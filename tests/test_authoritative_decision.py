"""Regression tests for the real, single authoritative decision object
(2026-09-02, Phase 5D - convert forensic findings into the authoritative
decision)."""
from types import SimpleNamespace

from fpl_agent.optimization.authoritative_decision import (
    CandidateAssessment,
    assess_candidate,
    build_authoritative_decision,
)


def _seed_pool(conn):
    now = "2026-01-01T00:00:00Z"
    conn.execute(f"INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Team A','TMA','{now}')")
    conn.execute(f"INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (2,2,'Team B','TMB','{now}')")
    conn.execute(
        f"INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, squad_min_play, "
        f"squad_max_play, squad_select, updated_at) VALUES (1,'Forward','FWD','Forwards',1,3,3,'{now}')"
    )
    for pid, team_id, name, price in ((1, 1, 'Owned', 50), (2, 2, 'Target', 50)):
        conn.execute(f"INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES ({pid},{pid},'{name}',{team_id},1,'a',0,'{now}')")
        conn.execute(f"INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) VALUES ({pid}, {price}, '{now}', NULL)")
    conn.commit()


def _step(event, out_id=None, out_name=None, in_id=None, in_name=None, chip=None, uses_hit=False, squad=()):
    return SimpleNamespace(
        event=event, player_out_id=out_id, player_out_name=out_name,
        player_in_id=in_id, player_in_name=in_name, chip_played=chip,
        uses_hit=uses_hit, resulting_squad_ids=squad,
    )


def _path(steps, total_net_ev, final_bank_tenths=0):
    return SimpleNamespace(steps=tuple(steps), total_net_ev=total_net_ev, final_bank_tenths=final_bank_tenths)


def _candidate(label, total_net_ev, strategic_class, immediate_action="ROLL", path=None):
    return CandidateAssessment(
        label=label, path=path or _path([], total_net_ev),
        total_net_ev=total_net_ev, immediate_gw_action=immediate_action,
        path_robustness_verdict="ROBUST" if strategic_class == "ROBUST" else "FRAGILE",
        price_robust=(strategic_class == "ROBUST"), strategic_class=strategic_class,
        credibility_label="LOW_FRICTION", reachable_successor_count=100,
        optionality_delta_vs_baseline=0,
    )


def _ca():
    current = SimpleNamespace(web_name="Haaland", median=6.32)
    return SimpleNamespace(current=current, decision_kind="keep", robustness="FRAGILE", options=())


class TestAssessCandidate:
    def test_smoke_wires_all_real_submodules_without_crashing(self, db_conn):
        _seed_pool(db_conn)
        path = _path([_step(3, 1, "Owned", 2, "Target", squad=(2,))], total_net_ev=10.0)
        from fpl_agent.optimization.future_optionality import assess_future_optionality
        baseline = assess_future_optionality(db_conn, [1], bank_tenths=50)

        result = assess_candidate(db_conn, "TEST", path, baseline, starting_bank_tenths=50)

        assert result.label == "TEST"
        assert result.total_net_ev == 10.0
        assert result.strategic_class in ("ROBUST", "FRAGILE", "UNRESOLVED")


class TestBuildAuthoritativeDecisionSelection:
    def test_top_candidate_chosen_when_gap_survives_haircut(self):
        candidates = [_candidate("A", 475.0, "FRAGILE"), _candidate("B", 400.0, "FRAGILE")]
        decision = build_authoritative_decision(candidates, _ca(), roll_baseline_ev=375.0)
        assert decision.immediate_action.startswith("A:")
        assert decision.best_alternative.startswith("B:")

    def test_walks_down_past_a_fragile_top_pick_with_a_tiny_gap(self):
        candidates = [
            _candidate("A", 475.0, "FRAGILE"),   # gap to B is only 2.0 - fails haircut
            _candidate("B", 473.0, "FRAGILE"),   # gap to C is 60.0 - clears haircut
            _candidate("C", 413.0, "FRAGILE"),
        ]
        decision = build_authoritative_decision(candidates, _ca(), roll_baseline_ev=375.0)
        assert decision.immediate_action.startswith("B:")
        assert decision.best_alternative.startswith("C:")

    def test_robust_top_candidate_is_chosen_even_with_a_tiny_gap(self):
        candidates = [_candidate("A", 400.5, "ROBUST"), _candidate("B", 400.0, "FRAGILE")]
        decision = build_authoritative_decision(candidates, _ca(), roll_baseline_ev=375.0)
        assert decision.immediate_action.startswith("A:")

    def test_falls_back_to_last_candidate_when_no_gap_ever_survives(self):
        candidates = [_candidate("A", 400.0, "FRAGILE"), _candidate("B", 399.0, "FRAGILE"), _candidate("C", 398.0, "FRAGILE")]
        decision = build_authoritative_decision(candidates, _ca(), roll_baseline_ev=375.0)
        assert decision.immediate_action.startswith("C:")
        assert decision.best_alternative == "none (only one real candidate)"


class TestDecisionStateAndActionType:
    def test_act_when_advantage_vs_roll_is_large(self):
        candidates = [_candidate("A", 475.0, "FRAGILE")]
        decision = build_authoritative_decision(candidates, _ca(), roll_baseline_ev=375.0)
        assert decision.decision_state == "ACT"

    def test_review_when_advantage_vs_roll_is_tiny_and_class_not_robust(self):
        candidates = [_candidate("A", 376.0, "FRAGILE")]
        decision = build_authoritative_decision(candidates, _ca(), roll_baseline_ev=375.0)
        assert decision.decision_state == "REVIEW"

    def test_act_when_robust_even_with_tiny_advantage_vs_roll(self):
        candidates = [_candidate("A", 376.0, "ROBUST")]
        decision = build_authoritative_decision(candidates, _ca(), roll_baseline_ev=375.0)
        assert decision.decision_state == "ACT"

    def test_action_type_chip_when_first_step_is_a_chip(self):
        path = _path([_step(3, chip="wildcard")], total_net_ev=475.0)
        candidates = [_candidate("A", 475.0, "ROBUST", "PLAY WILDCARD (GW3)", path=path)]
        decision = build_authoritative_decision(candidates, _ca(), roll_baseline_ev=375.0)
        assert decision.action_type == "CHIP"

    def test_action_type_transfer_when_first_step_is_a_plain_transfer(self):
        path = _path([_step(3, 1, "Out", 2, "In")], total_net_ev=475.0)
        candidates = [_candidate("A", 475.0, "ROBUST", path=path)]
        decision = build_authoritative_decision(candidates, _ca(), roll_baseline_ev=375.0)
        assert decision.action_type == "TRANSFER"

    def test_action_type_roll_when_first_step_is_empty(self):
        path = _path([_step(3)], total_net_ev=475.0)
        candidates = [_candidate("A", 475.0, "ROBUST", path=path)]
        decision = build_authoritative_decision(candidates, _ca(), roll_baseline_ev=375.0)
        assert decision.action_type == "ROLL"


class TestConditionalPlanSeparation:
    def test_first_step_excluded_from_future_conditional_plan(self):
        path = _path([_step(3, chip="wildcard"), _step(4, chip="3xc"), _step(5, chip="bboost")], total_net_ev=475.0)
        candidates = [_candidate("A", 475.0, "ROBUST", "PLAY WILDCARD (GW3)", path=path)]
        decision = build_authoritative_decision(candidates, _ca(), roll_baseline_ev=375.0)
        assert len(decision.future_conditional_plan) == 2
        assert all("NOT locked in" in step for step in decision.future_conditional_plan)
        assert not any("GW3" in step for step in decision.future_conditional_plan)

    def test_critical_dependencies_excludes_the_immediate_action_event(self):
        path = _path([
            _step(3, chip="wildcard"),
            _step(7, 5, "Wieffer", 6, "Van Hecke"),
        ], total_net_ev=475.0)
        candidates = [_candidate("A", 475.0, "ROBUST", "PLAY WILDCARD (GW3)", path=path)]
        decision = build_authoritative_decision(candidates, _ca(), roll_baseline_ev=375.0)
        assert decision.critical_dependencies == ("GW7 Wieffer -> Van Hecke",)
