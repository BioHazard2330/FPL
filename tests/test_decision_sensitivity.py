from types import SimpleNamespace

import fpl_agent.models.expected_points as ep_mod
import fpl_agent.models.minutes_distribution as md_mod
import fpl_agent.optimization.decision_sensitivity as ds_mod
from fpl_agent.models.expected_minutes import ExpectedMinutes
from fpl_agent.optimization.decision_sensitivity import _perturbed_minutes, stress_test_transfer


def _em(pid, minutes):
    return ExpectedMinutes(player_id=pid, expected_minutes=minutes, confidence="MEDIUM", basis="x", classification="FIT")


def test_perturbed_minutes_scales_the_targeted_player_only(monkeypatch):
    monkeypatch.setattr(md_mod, "expected_minutes", lambda conn, pid: _em(pid, 80.0))

    with _perturbed_minutes({1: 0.5}):
        assert md_mod.expected_minutes(None, 1).expected_minutes == 40.0
        assert md_mod.expected_minutes(None, 2).expected_minutes == 80.0  # not in overrides - untouched


def test_perturbed_minutes_patches_both_module_bindings(monkeypatch):
    """Real regression guard for the exact bug found building this (2026-08-26):
    `expected_minutes` is imported separately into expected_points.py AND
    minutes_distribution.py - patching only one binding silently makes a
    stress-test scenario reach nothing, since minutes_distribution.py's own
    binding is what actually drives the scoring path."""
    monkeypatch.setattr(ep_mod, "expected_minutes", lambda conn, pid: _em(pid, 80.0))
    monkeypatch.setattr(md_mod, "expected_minutes", lambda conn, pid: _em(pid, 80.0))

    with _perturbed_minutes({1: 0.5}):
        assert ep_mod.expected_minutes(None, 1).expected_minutes == 40.0
        assert md_mod.expected_minutes(None, 1).expected_minutes == 40.0


def test_perturbed_minutes_restores_on_exit_even_after_an_error(monkeypatch):
    monkeypatch.setattr(md_mod, "expected_minutes", lambda conn, pid: _em(pid, 80.0))
    real_fn = md_mod.expected_minutes

    try:
        with _perturbed_minutes({1: 0.5}):
            raise ValueError("boom")
    except ValueError:
        pass

    assert md_mod.expected_minutes is real_fn


def test_stress_test_transfer_labels_baseline_and_each_scenario_by_the_real_threshold(monkeypatch):
    calls = {"n": 0}

    def fake_evaluate_transfer(conn, out_id, in_id, is_hit, from_event=None):
        calls["n"] += 1
        ev = 5.0 if calls["n"] == 1 else 0.5  # baseline clears the bar, every scenario drops below it
        return SimpleNamespace(net_ev_3gw=ev)

    monkeypatch.setattr(ds_mod, "evaluate_transfer", fake_evaluate_transfer)

    report = stress_test_transfer(None, player_out_id=1, player_in_id=2, from_event=1)

    assert report.baseline_net_ev_3gw == 5.0
    assert report.baseline_decision == "transfer"
    assert len(report.scenarios) == 7
    assert all(s.decision_under_scenario == "roll" for s in report.scenarios)
    assert calls["n"] == 8  # 1 baseline + 7 scenarios


def test_stress_test_transfer_reports_no_flip_when_ev_never_drops_below_threshold(monkeypatch):
    monkeypatch.setattr(
        ds_mod, "evaluate_transfer",
        lambda conn, out_id, in_id, is_hit, from_event=None: SimpleNamespace(net_ev_3gw=10.0),
    )

    report = stress_test_transfer(None, player_out_id=1, player_in_id=2, from_event=1)

    assert report.baseline_decision == "transfer"
    assert all(s.decision_under_scenario == "transfer" for s in report.scenarios)
