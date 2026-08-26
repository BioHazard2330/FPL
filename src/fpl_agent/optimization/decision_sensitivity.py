"""Real counterfactual / sensitivity stress test for a chosen transfer
decision (2026-08-26, decision-quality audit, section 14). Answers "at what
assumption does TRANSFER flip to ROLL" directly, rather than leaving a bare
ROBUST label to stand in for that question.

Perturbs expected_minutes() at the exact call boundary expected_points.py
itself uses (a real, controlled monkeypatch of the module-global function
reference, restored immediately after each scenario) - this deliberately
never touches expected_points()/expected_points_window()'s own locked
public signature (see that module's own docstring: those signatures are
locked). Every other real input (fixture difficulty, team strength,
qualitative adjustments) stays exactly as the live model already computes -
only the ONE named assumption under test changes, so `evaluate_transfer`'s
exact real formula (net_ev_3gw = window(in).median - window(out).median -
hit_cost) is reused unchanged, never reimplemented or reweighted.
"""
import dataclasses
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass

import fpl_agent.models.expected_points as ep_mod
import fpl_agent.models.minutes_distribution as md_mod
from fpl_agent.optimization.transfers import evaluate_transfer

_TRANSFER_DELTA_THRESHOLD = 1.0  # same real bar decision_analysis.py uses - not redefined independently


@contextmanager
def _perturbed_minutes(overrides: dict[int, float]):
    """overrides: {player_id: multiplier} - e.g. {557: 0.85} means "this
    player's real expected_minutes() output, scaled 15% down for this one
    scenario only". Restored unconditionally on exit, including on error.

    Real gap found and fixed while building this (2026-08-26): `expected_minutes`
    is imported separately into TWO modules - `expected_points.py` (where the
    result is only used for the ExpectedPoints object's own display fields,
    `confidence`/`expected_minutes`) AND `minutes_distribution.py` (where it is
    the ACTUAL anchor for `minutes_bucket_probabilities()`'s `nonzero_fraction`,
    which is what genuinely drives appearance/goals/assists/bonus/clean-sheet/
    defcon). Both are real, live bindings of the same underlying function - in
    live production they always see the same real answer, so this is not a
    production bug, only an architectural quirk that patching just one binding
    (an earlier draft of this function did exactly that) silently misses. Both
    are patched here so a stress-test scenario genuinely reaches the real
    scoring path, not just the ExpectedPoints object's cosmetic label."""
    real_fn = md_mod.expected_minutes

    def patched(conn, pid):
        result = real_fn(conn, pid)
        if pid in overrides:
            new_minutes = min(round(result.expected_minutes * overrides[pid], 1), 90.0)
            result = dataclasses.replace(result, expected_minutes=new_minutes)
        return result

    ep_mod.expected_minutes = patched
    md_mod.expected_minutes = patched
    try:
        yield
    finally:
        ep_mod.expected_minutes = real_fn
        md_mod.expected_minutes = real_fn


@dataclass(frozen=True)
class SensitivityScenario:
    name: str
    description: str
    net_ev_3gw: float
    decision_under_scenario: str  # "transfer" | "roll" - pure EV-vs-threshold, not the full REVIEW gate


@dataclass(frozen=True)
class SensitivityReport:
    baseline_net_ev_3gw: float
    baseline_decision: str
    scenarios: tuple[SensitivityScenario, ...]


def stress_test_transfer(
    conn: sqlite3.Connection, player_out_id: int, player_in_id: int, from_event: int, is_hit: bool = False,
) -> SensitivityReport:
    baseline = evaluate_transfer(conn, player_out_id, player_in_id, is_hit, from_event=from_event)
    baseline_decision = "transfer" if baseline.net_ev_3gw >= _TRANSFER_DELTA_THRESHOLD else "roll"

    scenario_defs = [
        ("sold_player_minutes_-15%", "player being SOLD gets 15% fewer real minutes than currently projected", {player_out_id: 0.85}),
        ("sold_player_minutes_+15%", "player being SOLD gets 15% more real minutes than currently projected", {player_out_id: 1.15}),
        ("replacement_minutes_-15%", "REPLACEMENT gets 15% fewer real minutes than currently projected", {player_in_id: 0.85}),
        ("replacement_minutes_+15%", "REPLACEMENT gets 15% more real minutes than currently projected", {player_in_id: 1.15}),
        ("replacement_rotates_hard_-30%", "REPLACEMENT rotates hard - 30% fewer real minutes than currently projected", {player_in_id: 0.70}),
        ("worst_case_for_the_transfer", "sold player over-performs (+15% minutes) while the replacement under-performs (-15% minutes)", {player_out_id: 1.15, player_in_id: 0.85}),
        ("best_case_for_the_transfer", "sold player under-performs (-15% minutes) while the replacement over-performs (+15% minutes)", {player_out_id: 0.85, player_in_id: 1.15}),
    ]

    scenarios = []
    for name, desc, overrides in scenario_defs:
        with _perturbed_minutes(overrides):
            cand = evaluate_transfer(conn, player_out_id, player_in_id, is_hit, from_event=from_event)
        decision = "transfer" if cand.net_ev_3gw >= _TRANSFER_DELTA_THRESHOLD else "roll"
        scenarios.append(SensitivityScenario(
            name=name, description=desc, net_ev_3gw=cand.net_ev_3gw, decision_under_scenario=decision,
        ))

    return SensitivityReport(
        baseline_net_ev_3gw=baseline.net_ev_3gw, baseline_decision=baseline_decision, scenarios=tuple(scenarios),
    )
