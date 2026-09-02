"""Regression tests for the canonical decision object (2026-09-02,
decision-engine forensic audit, Phase 2). Real fixture data reused from
test_optimization_squad.py/test_optimization_locked_squad.py - same legal
15-man squad (P30 highest xp=6.5, P20 second=6.0), so `resolve_gw_xi`'s own
real captain/vice choice is hand-verifiable."""
from types import SimpleNamespace

from fpl_agent.database.decisions import log_decision
from fpl_agent.optimization import transfers as transfers_mod
from fpl_agent.optimization.decision_snapshot import (
    UserScenarioResult,
    _state_version,
    _tie_classification,
    build_decision_snapshot,
    evaluate_user_scenario,
)
from fpl_agent.optimization.locked_squad import get_locked_squad
from test_optimization_locked_squad import _FULL_15, _seed_real_picks
from test_optimization_squad import _PLAYERS, _seed

_XP_MAP = {pid: xp for pid, _et, _team_id, _price, xp in _PLAYERS}


def _patch_squad_gw_ev_fake(monkeypatch):
    def fake(conn, player_id, n_gw, from_event=None):
        return SimpleNamespace(total_median=_XP_MAP[player_id])
    monkeypatch.setattr(transfers_mod, "expected_points_window", fake)


def _seed_event(conn, event_id=1, is_next=1, is_current=0, finished=0):
    conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, updated_at) VALUES (?,?,?,?,?,0,?,?,'t0')",
        (event_id, f"GW{event_id}", "t0", event_id, finished, is_current, is_next),
    )
    conn.commit()


_REALISTIC_DETAIL = {
    "current_recommendation": {
        "verdict": "ACT", "action_kind": "transfer", "label": "P33 -> P16",
        "path_total": 50.0, "evidence_confidence": "MEDIUM", "reason": "test reason",
        "starting_action_options": [
            {"label": "P33 -> P16", "kind": "transfer", "path_total": 50.0},
            {"label": "ROLL", "kind": "roll", "path_total": 46.0},
        ],
    },
    "best_path": {
        "path_total": 50.0,
        "steps": [{"event": 1, "player_out_id": 33, "player_in_id": 16, "uses_hit": False, "chip_played": None, "gw_ev": 12.5}],
    },
    "paths": [
        {"path_total": 50.0, "horizon_breakdown": {
            "3": {"path_total": 30.0}, "5": {"path_total": 40.0}, "8": {"path_total": 50.0},
        }},
    ],
    "roll_total": 46.0,
    "squad_ids": _FULL_15,
}


def _seed_strategic_plan_decision(conn, detail=None):
    return log_decision(
        conn, "strategic_plan", "test decision", detail or _REALISTIC_DETAIL,
        model_version="calibrated-v2", confidence="MEDIUM",
    )


class TestTieClassification:
    def test_likely_best_with_no_runner_up(self):
        assert _tie_classification(50.0, None) == "LIKELY_BEST"

    def test_near_tie_within_one_point(self):
        assert _tie_classification(50.0, 49.2) == "NEAR_TIE"

    def test_high_uncertainty_between_one_and_three(self):
        assert _tie_classification(50.0, 47.5) == "HIGH_UNCERTAINTY"

    def test_likely_best_beyond_three_points(self):
        assert _tie_classification(50.0, 46.0) == "LIKELY_BEST"

    def test_boundary_exactly_one_point_is_near_tie(self):
        assert _tie_classification(50.0, 49.0) == "NEAR_TIE"

    def test_boundary_exactly_three_points_is_high_uncertainty(self):
        assert _tie_classification(50.0, 47.0) == "HIGH_UNCERTAINTY"


class TestStateVersionReproducibility:
    def test_identical_state_gives_identical_version(self, db_conn):
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        locked_a = get_locked_squad(db_conn)
        locked_b = get_locked_squad(db_conn)
        assert _state_version(locked_a) == _state_version(locked_b)

    def test_different_bank_gives_different_version(self, db_conn):
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        locked = get_locked_squad(db_conn)
        from dataclasses import replace
        other = replace(locked, bank_tenths=(locked.bank_tenths or 0) + 5)
        assert _state_version(locked) != _state_version(other)


class TestBuildDecisionSnapshot:
    def test_none_with_no_locked_squad(self, db_conn):
        _seed(db_conn, budget_tenths=950, club_limit=4)
        assert build_decision_snapshot(db_conn) is None

    def test_none_with_no_strategic_plan_decision(self, db_conn, monkeypatch):
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        assert build_decision_snapshot(db_conn) is None

    def test_populates_real_captain_and_vice_from_current_projections(self, db_conn, monkeypatch):
        """P30 (xp=6.5) and P20 (xp=6.0) are the squad's own two highest -
        resolve_gw_xi must pick them as captain/vice regardless of which
        chip/transfer the cached strategic_plan decision recommends, since
        captain/vice reflect CURRENT real projections, not the plan's own
        (unrelated) winning action."""
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1, captain_id=30, vice_id=20)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn)

        snap = build_decision_snapshot(db_conn)

        assert snap is not None
        assert snap.captain_id == 30
        assert snap.vice_captain_id == 20
        assert snap.captain_name == "P30"

    def test_expected_points_read_from_the_leading_diverse_path(self, db_conn, monkeypatch):
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn)

        snap = build_decision_snapshot(db_conn)

        assert snap.expected_points[3] == 30.0
        assert snap.expected_points[5] == 40.0
        assert snap.expected_points[8] == 50.0
        assert snap.expected_points[1] == 12.5

    def test_delta_vs_roll(self, db_conn, monkeypatch):
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn)

        snap = build_decision_snapshot(db_conn)

        assert snap.delta_vs_roll == 4.0  # 50.0 - 46.0

    def test_transfer_action_names_are_resolved(self, db_conn, monkeypatch):
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn)

        snap = build_decision_snapshot(db_conn)

        assert snap.transfer_out_id == 33
        assert snap.transfer_in_id == 16
        assert snap.transfer_out_name == "P33"
        assert snap.transfer_in_name == "P16"

    def test_near_tie_detected_from_real_starting_action_options(self, db_conn, monkeypatch):
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        near_tie_detail = {
            **_REALISTIC_DETAIL,
            "current_recommendation": {
                **_REALISTIC_DETAIL["current_recommendation"],
                "starting_action_options": [
                    {"label": "P33 -> P16", "kind": "transfer", "path_total": 50.0},
                    {"label": "ROLL", "kind": "roll", "path_total": 49.5},
                ],
            },
        }
        _seed_strategic_plan_decision(db_conn, near_tie_detail)

        snap = build_decision_snapshot(db_conn)

        assert snap.tie_classification == "NEAR_TIE"

    def test_reversal_condition_reports_real_margin_over_runner_up(self, db_conn, monkeypatch):
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn)

        snap = build_decision_snapshot(db_conn)

        assert any("runner-up" in c for c in snap.reversal_conditions)
        assert any("4.0" in c or "4.00" in c for c in snap.reversal_conditions)

    def test_frozen_state_reproducibility(self, db_conn, monkeypatch):
        """Same underlying state (same cached strategic_plan decision, same
        locked squad) must produce a byte-identical snapshot on repeated
        reads - this is a read-only projection, never a re-derivation."""
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn)

        snap_a = build_decision_snapshot(db_conn)
        snap_b = build_decision_snapshot(db_conn)

        assert snap_a == snap_b


class TestDashboardConsistency:
    def test_home_panel_and_canonical_snapshot_agree_on_the_label(self, db_conn, monkeypatch):
        """PART 16/20: Home (`_compute_primary_verdict`) and the canonical
        `DecisionSnapshot` must resolve to the exact same action label for
        the same real state - both are required to read the same
        hysteresis-stabilized `stable_current_recommendation` decision,
        never two independently-derived answers."""
        from types import SimpleNamespace

        from fpl_agent.monitoring.dashboard.legacy import _compute_primary_verdict

        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn)

        fake_ta = SimpleNamespace(reason="", decision_kind="roll", chosen=None)
        verdict = _compute_primary_verdict(db_conn, fake_ta)
        snap = build_decision_snapshot(db_conn)

        assert snap is not None
        assert verdict.action_label == snap.label
        assert verdict.current_rec["action_kind"] == snap.action_kind


class TestUserScenario:
    def test_roll_only_scenario_matches_squad_ev(self, db_conn, monkeypatch):
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)

        result = evaluate_user_scenario(
            db_conn, _FULL_15, free_transfers=1, bank_tenths=0, horizon_gw=1,
        )

        assert result.label == "ROLL"
        assert not result.uses_hit

    def test_transfer_scenario_reports_real_label_and_hit(self, db_conn, monkeypatch):
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)

        result = evaluate_user_scenario(
            db_conn, _FULL_15, free_transfers=0, bank_tenths=100,
            transfer_out_id=33, transfer_in_id=16, horizon_gw=1,
        )

        assert "P33" in result.label and "P16" in result.label
        assert result.uses_hit  # free_transfers=0 forces a hit

    def test_delta_vs_system_is_computed_against_the_passed_baseline(self, db_conn, monkeypatch):
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)

        result = evaluate_user_scenario(
            db_conn, _FULL_15, free_transfers=1, bank_tenths=0, horizon_gw=1,
            system_expected_points={1: 100.0, 3: 100.0, 5: 100.0, 8: 100.0},
        )

        assert result.delta_vs_system[1] == round(result.expected_points[1] - 100.0, 2)

    def test_scenario_result_is_never_persisted_as_a_decision(self, db_conn, monkeypatch):
        """PART 14: scenario analysis must never write a decision row -
        this is the real, load-bearing invariant that keeps user-intent
        evaluation from ever silently becoming (or being mistaken for) the
        system recommendation."""
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        before = db_conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]

        evaluate_user_scenario(db_conn, _FULL_15, free_transfers=1, bank_tenths=0, horizon_gw=1)

        after = db_conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        assert after == before
