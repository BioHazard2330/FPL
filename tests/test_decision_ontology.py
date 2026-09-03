"""Regression tests for the real, unified decision-state vocabulary
(2026-09-02, Phase 5C optimizer forensic rebuild, PART 7)."""
from types import SimpleNamespace

from fpl_agent.optimization.decision_ontology import (
    advantage_survives_haircut,
    check_consistency,
    classify_strategic_class,
    resolve_action_given_class,
    unify_captain_decision,
    unify_path_decision,
    unify_transfer_decision,
)


def _ta(kind, uses_hit=False):
    chosen = SimpleNamespace(candidate=SimpleNamespace(uses_hit=uses_hit)) if kind == "transfer" else None
    return SimpleNamespace(decision_kind=kind, chosen=chosen)


def _ca(kind):
    return SimpleNamespace(decision_kind=kind)


class TestUnifyTransferDecision:
    def test_transfer_plus_wait(self):
        """PART 7's own required case: transfer + WAIT."""
        state, action = unify_transfer_decision(_ta("wait"))
        assert state == "WAIT"
        assert action == "TRANSFER"

    def test_roll_plus_hold(self):
        """PART 7's own required case: roll + HOLD."""
        state, action = unify_transfer_decision(_ta("roll"))
        assert state == "HOLD"
        assert action == "ROLL"

    def test_transfer_without_hit_is_act_transfer(self):
        state, action = unify_transfer_decision(_ta("transfer", uses_hit=False))
        assert state == "ACT"
        assert action == "TRANSFER"

    def test_transfer_with_hit_is_act_hit(self):
        state, action = unify_transfer_decision(_ta("transfer", uses_hit=True))
        assert state == "ACT"
        assert action == "HIT"

    def test_ambiguous_narrow_margin_review(self):
        """PART 7's own required case: ambiguous/narrow-margin + REVIEW."""
        state, action = unify_transfer_decision(_ta("review"))
        assert state == "REVIEW"
        assert action == "OTHER"


class TestUnifyCaptainDecision:
    def test_keep_is_hold_keep_captain(self):
        state, action = unify_captain_decision(_ca("keep"))
        assert state == "HOLD"
        assert action == "KEEP_CAPTAIN"

    def test_change_is_act(self):
        state, action = unify_captain_decision(_ca("change"))
        assert state == "ACT"

    def test_unavailable_degrades_to_review(self):
        state, action = unify_captain_decision(_ca("unavailable"))
        assert state == "REVIEW"


class TestUnifyPathDecision:
    def test_chip_plus_act(self):
        """PART 7's own required case: chip + ACT."""
        state, action = unify_path_decision("chip", "ACT")
        assert state == "ACT"
        assert action == "CHIP"

    def test_roll_plus_hold(self):
        state, action = unify_path_decision("roll", "ACT")
        assert state == "HOLD"
        assert action == "ROLL"

    def test_review_verdict_always_wins_regardless_of_action_kind(self):
        state, action = unify_path_decision("transfer", "REVIEW")
        assert state == "REVIEW"


class TestConsistencyCheck:
    def test_matching_states_are_not_contradictory(self):
        result = check_consistency(transfer_state="HOLD", path_state="HOLD")
        assert result.contradictory is False

    def test_act_vs_hold_on_the_same_axis_is_contradictory(self):
        result = check_consistency(transfer_state="ACT", path_state="HOLD")
        assert result.contradictory is True
        assert "SAME real transfer-this-gameweek axis" in result.note

    def test_act_vs_review_is_contradictory(self):
        result = check_consistency(transfer_state="ACT", path_state="REVIEW")
        assert result.contradictory is True

    def test_wait_vs_wait_is_not_contradictory(self):
        result = check_consistency(transfer_state="WAIT", path_state="WAIT")
        assert result.contradictory is False

    def test_missing_layer_never_forces_a_false_contradiction(self):
        result = check_consistency(transfer_state="ACT", path_state=None)
        assert result.contradictory is False


class TestClassifyStrategicClass:
    def test_robust_requires_both_path_and_price_robust(self):
        assert classify_strategic_class("ROBUST", True) == "ROBUST"

    def test_robust_path_but_price_fragile_is_fragile_overall(self):
        assert classify_strategic_class("ROBUST", False) == "FRAGILE"

    def test_fragile_path_is_fragile_regardless_of_price(self):
        assert classify_strategic_class("FRAGILE", True) == "FRAGILE"

    def test_moderate_path_is_fragile_not_robust(self):
        assert classify_strategic_class("MODERATE", True) == "FRAGILE"

    def test_unstressed_path_is_unresolved(self):
        assert classify_strategic_class("UNSTRESSED", True) == "UNRESOLVED"

    def test_missing_price_check_is_unresolved(self):
        assert classify_strategic_class("ROBUST", None) == "UNRESOLVED"


class TestAdvantageSurvivesHaircut:
    def test_large_advantage_survives_30_percent_haircut(self):
        """Real Phase 5C figure: Wildcard's 45.31pt marginal (45.31*0.7=31.7,
        well clear of the real 3.0 non-coincidental-lead floor)."""
        assert advantage_survives_haircut(45.31) is True

    def test_small_advantage_does_not_survive_30_percent_haircut(self):
        """Real Phase 5C figure: Free Hit's 4.07pt marginal (4.07*0.7=2.85,
        under the real 3.0 floor) does not clear the bar."""
        assert advantage_survives_haircut(4.07) is False

    def test_zero_advantage_never_survives(self):
        assert advantage_survives_haircut(0.0) is False

    def test_negative_advantage_never_survives(self):
        assert advantage_survives_haircut(-5.0) is False


class TestResolveActionGivenClass:
    def test_robust_always_acts_even_with_tiny_advantage(self):
        assert resolve_action_given_class("ROBUST", 0.5) == "ACT"

    def test_fragile_with_large_advantage_still_acts(self):
        """The optimizer MAY still select a FRAGILE path when its real EV
        advantage is genuinely large - this is the required non-veto case
        (real Phase 5C Wildcard figure)."""
        assert resolve_action_given_class("FRAGILE", 45.31) == "ACT"

    def test_fragile_with_tiny_advantage_downgrades_to_review(self):
        """A tiny fragile advantage must never masquerade as a robust one -
        this is the required veto case (real Phase 5C Free Hit figure)."""
        assert resolve_action_given_class("FRAGILE", 4.07) == "REVIEW"

    def test_unresolved_never_silently_acts(self):
        assert resolve_action_given_class("UNRESOLVED", 999.0) == "REVIEW"
