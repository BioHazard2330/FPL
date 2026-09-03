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


class TestPathCredibilityAndRobustness:
    """Real whole-path credibility/robustness wiring (2026-09-02, Phase 5
    optimizer forensic rebuild PART 9/10/20) - `robustness` used to be
    hard-coded `None` on every real snapshot. These tests cover the WIRING
    in `build_decision_snapshot` (the `_path_adapter` bridge + `risks`
    aggregation), not `path_credibility.py`/`strategy_robustness.py`'s own
    internal logic, which has its own dedicated test files."""

    def test_credibility_and_robustness_are_populated_not_none(self, db_conn, monkeypatch):
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn)
        import fpl_agent.optimization.decision_snapshot as ds_mod

        monkeypatch.setattr(
            ds_mod, "assess_path_credibility",
            lambda conn, path: SimpleNamespace(credibility_label="HIGH_FRICTION", reasons=("real reason A", "real reason B")),
        )
        monkeypatch.setattr(
            ds_mod, "assess_path_robustness",
            lambda conn, path: SimpleNamespace(verdict="FRAGILE", reason="real weakest-link reason"),
        )

        snap = build_decision_snapshot(db_conn)

        assert snap.path_credibility == "HIGH_FRICTION"
        assert snap.path_robustness == "FRAGILE"
        assert "real reason A" in snap.risks
        assert "real weakest-link reason" in snap.risks

    def test_low_friction_and_robust_paths_do_not_pollute_risks(self, db_conn, monkeypatch):
        """A genuinely clean path must not manufacture a risk entry just
        because the assessment ran - `risks` stays real and sparse."""
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn)
        import fpl_agent.optimization.decision_snapshot as ds_mod

        monkeypatch.setattr(
            ds_mod, "assess_path_credibility",
            lambda conn, path: SimpleNamespace(credibility_label="LOW_FRICTION", reasons=("no real concerns",)),
        )
        monkeypatch.setattr(
            ds_mod, "assess_path_robustness",
            lambda conn, path: SimpleNamespace(verdict="ROBUST", reason="every real step survives"),
        )

        snap = build_decision_snapshot(db_conn)

        assert snap.path_credibility == "LOW_FRICTION"
        assert snap.path_robustness == "ROBUST"
        assert snap.risks == ()

    def test_a_real_failure_in_credibility_assessment_degrades_honestly(self, db_conn, monkeypatch):
        """A real exception inside the new assessment must never crash the
        whole canonical snapshot - degrades to None fields, same posture
        every other optional real enrichment on this object already has."""
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn)
        import fpl_agent.optimization.decision_snapshot as ds_mod

        def _raise(conn, path):
            raise RuntimeError("real, unexpected failure")

        monkeypatch.setattr(ds_mod, "assess_path_credibility", _raise)

        snap = build_decision_snapshot(db_conn)

        assert snap is not None
        assert snap.path_credibility is None
        assert snap.path_robustness is None
        assert snap.risks == ()

    def test_optionality_note_is_actually_wired_into_the_return(self, db_conn, monkeypatch):
        """Real regression lock (2026-09-02, Phase 5B PART 2/8) - a real bug
        was found live: `optionality_note` was computed correctly but never
        passed to the `DecisionSnapshot(...)` constructor, so every real
        snapshot silently carried `None` regardless of the real computation
        succeeding. This test fails if that specific mistake recurs."""
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn)
        import fpl_agent.optimization.decision_snapshot as ds_mod

        import fpl_agent.optimization.future_optionality as fo_mod

        counts = iter([100, 60])  # baseline, then after - a real, honest shrink

        monkeypatch.setattr(
            fo_mod, "assess_future_optionality",
            lambda conn, squad_ids, bank_tenths, free_transfers=0: SimpleNamespace(
                reachable_successor_count=next(counts), premium_access_count=1,
            ),
        )

        snap = build_decision_snapshot(db_conn)

        assert snap.optionality_note is not None
        assert "reachable-successor" in snap.optionality_note
        # PART 1 (2026-09-02, Phase 5C) - every quantity in its own real,
        # unambiguous field, never only parseable out of the prose note.
        assert snap.baseline_reachable_successors == 100
        assert snap.reachable_successors == 60
        assert snap.optionality_delta == -40
        assert snap.optionality_percent_change == -40.0

    def test_fragile_captain_robustness_is_folded_into_path_level_risks(self, db_conn, monkeypatch):
        """PART 6 (2026-09-02, Phase 5C) - a real FRAGILE captain verdict
        (the existing, already-built `_attach_captain_robustness` engine,
        not rebuilt here) must be visible at path level, not siloed in a
        separate captain-only object."""
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1, captain_id=30, vice_id=20)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn)

        fake_ca = SimpleNamespace(robustness="FRAGILE", current=SimpleNamespace(web_name="TestCaptain"))

        snap = build_decision_snapshot(db_conn, ca=fake_ca)

        assert any("TestCaptain" in r and "FRAGILE" in r for r in snap.risks)

    def test_robust_captain_does_not_pollute_risks(self, db_conn, monkeypatch):
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1, captain_id=30, vice_id=20)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn)

        fake_ca = SimpleNamespace(robustness="ROBUST", current=SimpleNamespace(web_name="TestCaptain"))

        snap = build_decision_snapshot(db_conn, ca=fake_ca)

        assert not any("TestCaptain" in r for r in snap.risks)

    def test_passed_in_ca_is_used_not_recomputed(self, db_conn, monkeypatch):
        """The real "pass ta/ca in, never re-scan" pattern - a caller-supplied
        `ca` must be used as-is, never silently replaced by a fresh
        `analyze_captain_decision` call."""
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1, captain_id=30, vice_id=20)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn)
        import fpl_agent.optimization.decision_analysis as da_mod

        def _boom(conn, locked):
            raise AssertionError("analyze_captain_decision must not be called when ca is already provided")

        monkeypatch.setattr(da_mod, "analyze_captain_decision", _boom)
        fake_ca = SimpleNamespace(robustness="FRAGILE", current=SimpleNamespace(web_name="TestCaptain"))

        snap = build_decision_snapshot(db_conn, ca=fake_ca)

        assert any("TestCaptain" in r for r in snap.risks)


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


def _authoritative_detail(
    label, action_kind, action_type, *, path_total=475.64, chip_name=None,
    player_out_id=None, player_in_id=None, uses_hit=False, decision_state="ACT",
    best_path_chip=None, best_path_out_id=None, best_path_in_id=None,
):
    """Real (2026-09-02, Phase 5E) fixture builder - a full, self-consistent
    `current_recommendation.authoritative` block, matching the exact shape
    `cli/main.py`'s real `strategic_plan_cmd` now persists. `best_path_*`
    params let a test deliberately construct a `best_path` that DISAGREES
    with the authoritative pick - the real, confirmed historical bug
    (`label` said one thing, `best_path`'s own first step said another) this
    fixture exists to make reproducible."""
    return {
        "current_recommendation": {
            "verdict": "ACT" if decision_state == "ACT" else "REVIEW",
            "action_kind": action_kind, "label": label, "path_total": path_total,
            "evidence_confidence": "MEDIUM", "reason": "test reason",
            "starting_action_options": [{
                "label": label, "kind": action_kind, "path_total": path_total, "chip_name": chip_name,
                "player_out_id": player_out_id, "player_out_name": None,
                "player_in_id": player_in_id, "player_in_name": None, "uses_hit": uses_hit,
            }],
            "authoritative": {
                "decision_state": decision_state, "action_type": action_type,
                "immediate_action": f"{label}: test immediate action", "best_alternative": "TEST_ALT: test alt action",
                "nominal_ev_advantage": 10.0, "robustness_class": "ROBUST",
                "path_credibility": "LOW_FRICTION", "price_robustness": True,
                "optionality_effect": "test optionality effect string",
                "critical_dependencies": ["GW5 TestOut -> TestIn"], "captain_decision": "test captain string",
                "future_conditional_plan": ["GW5: test conditional leg"], "decision_reason": "mechanical test reason",
            },
            "authoritative_diagnostics": {
                "path_robustness_verdict": "ROBUST", "reachable_successor_count": 100,
                "optionality_delta_vs_baseline": 10,
            },
        },
        "best_path": {
            "path_total": path_total,
            "steps": [{
                "event": 1, "player_out_id": best_path_out_id, "player_in_id": best_path_in_id,
                "uses_hit": False, "chip_played": best_path_chip, "gw_ev": 10.0,
            }],
        },
        "paths": [{"path_total": path_total, "horizon_breakdown": {
            "3": {"path_total": path_total * 0.3}, "5": {"path_total": path_total * 0.5}, "8": {"path_total": path_total},
        }}],
        "roll_total": path_total - 10.0,
        "squad_ids": _FULL_15,
    }


class TestAuthoritativeDecisionWiring:
    """Real (2026-09-02, Phase 5E - "wire the authoritative decision into
    production") regression tests for PART 1 (single source of truth),
    PART 3 (remove stale-cache authority), and PART 10 (one-source-of-truth
    invariant)."""

    def test_chip_identity_comes_from_the_authoritative_pick_not_best_path(self, db_conn, monkeypatch):
        """THE real, confirmed historical bug this phase closes: `label`
        said "PLAY WILDCARD" while `chip` was silently still reading
        "freehit" off a DIFFERENT, un-authoritative `best_path`. Constructs
        that exact disagreement on purpose and proves the snapshot now
        reports the authoritative pick, never `best_path`'s."""
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        detail = _authoritative_detail(
            "PLAY WILDCARD", "chip", "CHIP", chip_name="wildcard",
            best_path_chip="freehit",  # deliberately disagreeing stale path
        )
        _seed_strategic_plan_decision(db_conn, detail)

        snap = build_decision_snapshot(db_conn)

        assert snap.label == "PLAY WILDCARD"
        assert snap.chip == "wildcard"
        assert snap.chip != "freehit"

    def test_transfer_identity_comes_from_the_authoritative_pick_not_best_path(self, db_conn, monkeypatch):
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        detail = _authoritative_detail(
            "P33 -> P16", "transfer", "TRANSFER", player_out_id=33, player_in_id=16,
            best_path_out_id=99, best_path_in_id=98,  # a DIFFERENT, disagreeing stale pair
        )
        _seed_strategic_plan_decision(db_conn, detail)

        snap = build_decision_snapshot(db_conn)

        assert snap.transfer_out_id == 33
        assert snap.transfer_in_id == 16

    def test_stale_older_decision_never_overrides_a_fresher_one(self, db_conn, monkeypatch):
        """PART 3: an older FREEHIT recommendation logged first, a newer
        WILDCARD recommendation with a real, meaningful EV advantage (>=5.0
        path_total points, this project's own existing `decision_hysteresis.
        py::_MIN_EV_ADVANTAGE` bar - a real, deliberate, pre-existing
        anti-flip-flop gate, not bypassed here) logged after - the snapshot
        must resolve to the fresher one, not get stuck on the stale one."""
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn, _authoritative_detail("PLAY FREEHIT", "chip", "CHIP", chip_name="freehit", path_total=460.0))
        _seed_strategic_plan_decision(db_conn, _authoritative_detail("PLAY WILDCARD", "chip", "CHIP", chip_name="wildcard", path_total=475.64))

        snap = build_decision_snapshot(db_conn)

        assert snap.label == "PLAY WILDCARD"
        assert snap.chip == "wildcard"

    def test_inverse_stale_mechanism_is_general_not_a_wildcard_special_case(self, db_conn, monkeypatch):
        """Same mechanism, reversed order and reversed EV advantage - proves
        this is real recency+materiality resolution, never a hard-coded
        "wildcard beats freehit" special case."""
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn, _authoritative_detail("PLAY WILDCARD", "chip", "CHIP", chip_name="wildcard", path_total=475.64))
        _seed_strategic_plan_decision(db_conn, _authoritative_detail("PLAY FREEHIT", "chip", "CHIP", chip_name="freehit", path_total=490.0))

        snap = build_decision_snapshot(db_conn)

        assert snap.label == "PLAY FREEHIT"
        assert snap.chip == "freehit"

    def test_decision_snapshot_fields_populated_verbatim_from_authoritative(self, db_conn, monkeypatch):
        """PART 2: the production DecisionSnapshot must be populated FROM
        the authoritative decision, field for field, never re-derived."""
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn, _authoritative_detail("PLAY WILDCARD", "chip", "CHIP", chip_name="wildcard"))

        snap = build_decision_snapshot(db_conn)

        assert snap.authoritative_is_fresh is True
        assert snap.decision_state == "ACT"
        assert snap.action_type == "CHIP"
        assert snap.immediate_action == "PLAY WILDCARD: test immediate action"
        assert snap.best_alternative == "TEST_ALT: test alt action"
        assert snap.nominal_ev_advantage == 10.0
        assert snap.robustness_class == "ROBUST"
        assert snap.price_robustness is True
        assert snap.optionality_effect == "test optionality effect string"
        assert snap.critical_dependencies == ("GW5 TestOut -> TestIn",)
        assert snap.future_conditional_plan == ("GW5: test conditional leg",)
        assert snap.decision_reason == "mechanical test reason"
        assert snap.path_credibility == "LOW_FRICTION"

    def test_legacy_row_without_authoritative_leaves_new_fields_honestly_none(self, db_conn, monkeypatch):
        """PART 9-adjacent: a pre-Phase-5E cached decision has no
        `authoritative` key - the new fields must be honestly `None`, never
        backfilled with a guess, and `authoritative_is_fresh` must say so."""
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn)  # _REALISTIC_DETAIL, no "authoritative" key

        snap = build_decision_snapshot(db_conn)

        assert snap.authoritative_is_fresh is False
        assert snap.decision_state is None
        assert snap.robustness_class is None
        assert snap.critical_dependencies == ()

    def test_captain_axis_never_overwrites_the_top_level_chip_decision(self, db_conn, monkeypatch):
        """PART 6: `ACT -> WILDCARD` and `KEEP -> HAALAND` must coexist
        without treating them as conflicting."""
        _seed(db_conn, budget_tenths=950, club_limit=4)
        _seed_real_picks(db_conn, event=1)
        _seed_event(db_conn)
        _patch_squad_gw_ev_fake(monkeypatch)
        _seed_strategic_plan_decision(db_conn, _authoritative_detail("PLAY WILDCARD", "chip", "CHIP", chip_name="wildcard"))
        fake_ca = SimpleNamespace(robustness="FRAGILE", decision_kind="keep", current=SimpleNamespace(web_name="Haaland", median=6.32))

        snap = build_decision_snapshot(db_conn, ca=fake_ca)

        assert snap.label == "PLAY WILDCARD"
        assert snap.decision_state == "ACT"
        assert snap.captain_decision is not None
        assert "Haaland" in snap.captain_decision
        assert "keep" in snap.captain_decision
