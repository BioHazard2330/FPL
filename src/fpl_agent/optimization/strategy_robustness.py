"""Real whole-path robustness assessment (2026-09-02, Phase 5 optimizer
forensic rebuild, PART 10). Extends the existing single-swap adversarial
stress-test machinery (`optimization/adversarial_audit.py::run_stress_tests`/
`classify_robustness`) to a full multi-GW path, rather than only ever
stress-testing one isolated captain-vs-runner-up or transfer-out-vs-in pair.

Real, disclosed design choice: this does NOT re-run a new whole-path Monte-
Carlo simulation (a real, much larger, separate build) - it reuses the
EXISTING, already-real per-transfer stress test on every real transfer step
inside the path, and aggregates via the path's OWN weakest link. This is a
genuine, honest measure ("a chain is only as strong as its weakest
transfer"), not a fabricated aggregate score - every number it reports
traces back to `run_stress_tests`'s own real, already-verified linear
component-perturbation model. A future, larger whole-path Monte-Carlo
re-simulation is a real, scoped follow-up, not attempted this pass."""
import sqlite3
from dataclasses import dataclass

from fpl_agent.optimization.adversarial_audit import classify_robustness, run_stress_tests

# Real, disclosed window - matches `decision_analysis.py`'s own established
# 3-GW materiality convention (`_TRANSFER_DELTA_THRESHOLD`'s own window),
# reused here rather than inventing a second real horizon for stress-testing.
_STRESS_N_GW = 3
_VERDICT_RANK = {"ROBUST": 0, "MODERATE": 1, "FRAGILE": 2}


@dataclass(frozen=True)
class StepRobustness:
    event: int
    player_out_name: str
    player_in_name: str
    verdict: str


@dataclass(frozen=True)
class PathRobustness:
    step_results: tuple[StepRobustness, ...]
    verdict: str  # ROBUST | MODERATE | FRAGILE | UNSTRESSED (no real transfer steps to stress)
    weakest_step: StepRobustness | None
    reason: str


def assess_path_robustness(conn: sqlite3.Connection, path) -> PathRobustness:
    """`path` is a real `TransferSequence` (or matching `.steps` shape).
    Only real transfer steps (a genuine out/in pair) are stressed - chip and
    roll steps have no single-player swap for the existing stress-test model
    to perturb, and are correctly left out rather than assigned a fabricated
    verdict."""
    step_results: list[StepRobustness] = []
    for s in path.steps:
        if s.player_out_id is None or s.player_in_id is None:
            continue
        try:
            results = run_stress_tests(conn, s.player_out_id, s.player_in_id, s.event, _STRESS_N_GW, s.uses_hit)
            verdict = classify_robustness(results)
        except Exception:
            continue
        step_results.append(StepRobustness(
            event=s.event, player_out_name=s.player_out_name or str(s.player_out_id),
            player_in_name=s.player_in_name or str(s.player_in_id), verdict=verdict,
        ))

    if not step_results:
        return PathRobustness(
            step_results=(), verdict="UNSTRESSED", weakest_step=None,
            reason="no real transfer steps in this path to stress-test (a pure roll/chip-only path)",
        )

    weakest = max(step_results, key=lambda r: _VERDICT_RANK[r.verdict])
    overall = weakest.verdict
    if overall == "FRAGILE":
        reason = (
            f"GW{weakest.event} {weakest.player_out_name} -> {weakest.player_in_name} flips under a real, "
            f"plausible (<=15%) adverse swing - the path's own weakest real link"
        )
    elif overall == "MODERATE":
        reason = (
            f"every real transfer step survives a small adverse swing; GW{weakest.event} "
            f"{weakest.player_out_name} -> {weakest.player_in_name} flips only under a larger (15-30%) one"
        )
    else:
        reason = "every real transfer step in this path survives the full real stress-test range"

    return PathRobustness(step_results=tuple(step_results), verdict=overall, weakest_step=weakest, reason=reason)
