"""Regression tests for real whole-path robustness assessment (2026-09-02,
Phase 5 optimizer forensic rebuild) - reuses the existing, already-real
`adversarial_audit.run_stress_tests`/`classify_robustness` per transfer step,
mocked here the same way `test_adversarial_audit.py` already does."""
from types import SimpleNamespace

import fpl_agent.optimization.strategy_robustness as sr_mod
from fpl_agent.optimization.strategy_robustness import assess_path_robustness


def _step(event, out_id=None, out_name=None, in_id=None, in_name=None, hit=False):
    return SimpleNamespace(event=event, player_out_id=out_id, player_out_name=out_name, player_in_id=in_id, player_in_name=in_name, uses_hit=hit)


def _path(steps):
    return SimpleNamespace(steps=steps)


def test_unstressed_for_a_pure_roll_or_chip_only_path(db_conn):
    path = _path([_step(3), _step(4)])

    result = assess_path_robustness(db_conn, path)

    assert result.verdict == "UNSTRESSED"
    assert result.step_results == ()


def test_robust_when_every_real_step_survives_stress(db_conn, monkeypatch):
    monkeypatch.setattr(sr_mod, "run_stress_tests", lambda conn, out_id, in_id, event, n_gw, uses_hit: [])
    monkeypatch.setattr(sr_mod, "classify_robustness", lambda results: "ROBUST")
    path = _path([_step(3, out_id=1, out_name="A", in_id=2, in_name="B")])

    result = assess_path_robustness(db_conn, path)

    assert result.verdict == "ROBUST"
    assert len(result.step_results) == 1


def test_overall_verdict_is_the_real_weakest_link(db_conn, monkeypatch):
    calls = {"n": 0}

    def fake_stress(conn, out_id, in_id, event, n_gw, uses_hit):
        calls["n"] += 1
        return []

    verdicts = iter(["ROBUST", "FRAGILE", "MODERATE"])
    monkeypatch.setattr(sr_mod, "run_stress_tests", fake_stress)
    monkeypatch.setattr(sr_mod, "classify_robustness", lambda results: next(verdicts))
    path = _path([
        _step(3, out_id=1, out_name="A", in_id=2, in_name="B"),
        _step(4, out_id=3, out_name="C", in_id=4, in_name="D"),
        _step(5, out_id=5, out_name="E", in_id=6, in_name="F"),
    ])

    result = assess_path_robustness(db_conn, path)

    assert calls["n"] == 3
    assert result.verdict == "FRAGILE"
    assert result.weakest_step.event == 4
    assert "C -> D" in result.reason


def test_chip_and_roll_steps_are_never_stressed(db_conn, monkeypatch):
    seen = []
    monkeypatch.setattr(sr_mod, "run_stress_tests", lambda conn, out_id, in_id, event, n_gw, uses_hit: seen.append(event) or [])
    monkeypatch.setattr(sr_mod, "classify_robustness", lambda results: "ROBUST")
    path = _path([
        _step(3),  # roll
        SimpleNamespace(event=4, player_out_id=None, player_out_name=None, player_in_id=None, player_in_name=None, uses_hit=False, chip_played="wildcard"),
        _step(5, out_id=1, out_name="A", in_id=2, in_name="B"),
    ])

    result = assess_path_robustness(db_conn, path)

    assert seen == [5]
    assert len(result.step_results) == 1
