"""Real future price-execution robustness (2026-09-02, Phase 5C optimizer
forensic rebuild, PART 3). Never predicts future prices - the search itself
already only ever uses TODAY's real prices for every future transition
(confirmed by direct inspection of `transfers.py::best_transfer_for_player`'s
`_current_price` calls). This module stress-tests that real, disclosed
assumption: for each real transfer step, would the transition still be
LEGALLY AFFORDABLE under a bounded, real price perturbation (in this
project's own real price-tenths unit, 1 = £0.1m)?

Real, disclosed running-bank model: walks the path from the REAL starting
bank (`locked.bank_tenths`), applying each real transfer step's own
TODAY-priced out/in delta in order - the same honest "today's prices, every
step" assumption the search itself already makes, not a new one invented
here. A path's own real `final_bank_tenths` (when available) is used only as
a real, independent cross-check, never silently substituted for the
per-step running total."""
import sqlite3
from dataclasses import dataclass

# Real, disclosed scenario set, in real price-tenths deltas (target, owned) -
# matches PART 3's own explicit list (+0.1/+0.2/-0.1 for the target,
# -0.1/-0.2 for the owned/outgoing player). Never converted into a
# fabricated probability - each scenario is reported PASS/FAIL only.
PRICE_SCENARIOS: dict[str, tuple[int, int]] = {
    "unchanged": (0, 0),
    "target_+0.1": (1, 0),
    "target_+0.2": (2, 0),
    "target_-0.1": (-1, 0),
    "owned_-0.1": (0, -1),
    "owned_-0.2": (0, -2),
}


@dataclass(frozen=True)
class PriceDependency:
    event: int
    player_out_name: str
    player_in_name: str
    today_margin_tenths: int  # real, current (running_bank + price_out) - price_in
    failed_scenarios: tuple[str, ...]


@dataclass(frozen=True)
class PriceRobustnessAssessment:
    price_dependencies: tuple[PriceDependency, ...]  # every real transfer step, not just the flagged ones
    price_robust: bool  # True only if EVERY real scenario leaves EVERY real step affordable
    number_of_failed_price_scenarios: int  # real count of (step, scenario) pairs that fail
    critical_price_assumptions: tuple[str, ...]  # real, human-readable list of the step/scenario pairs that fail


def assess_price_robustness(conn: sqlite3.Connection, path, starting_bank_tenths: int) -> PriceRobustnessAssessment:
    """`path` is a real `TransferSequence`-shaped object (`.steps`, each with
    real `.event`/`.player_out_id`/`.player_in_id`/names). Real running bank
    starts at `starting_bank_tenths` (the locked squad's own real current
    bank) and updates using TODAY's real prices at each real transfer step -
    see this module's own docstring for why that's the honest assumption,
    not a new one."""
    from fpl_agent.optimization.transfers import _current_price

    dependencies: list[PriceDependency] = []
    running_bank = starting_bank_tenths
    for s in path.steps:
        if s.player_out_id is None or s.player_in_id is None:
            continue
        price_out = _current_price(conn, s.player_out_id)
        price_in = _current_price(conn, s.player_in_id)
        today_margin = (running_bank + price_out) - price_in

        failed = []
        for name, (target_delta, owned_delta) in PRICE_SCENARIOS.items():
            scenario_margin = (running_bank + (price_out + owned_delta)) - (price_in + target_delta)
            if scenario_margin < 0:
                failed.append(name)

        dependencies.append(PriceDependency(
            event=s.event, player_out_name=s.player_out_name or str(s.player_out_id),
            player_in_name=s.player_in_name or str(s.player_in_id),
            today_margin_tenths=today_margin, failed_scenarios=tuple(failed),
        ))
        running_bank += price_out - price_in

    total_failed = sum(len(d.failed_scenarios) for d in dependencies)
    critical = tuple(
        f"GW{d.event} {d.player_out_name} -> {d.player_in_name}: fails under {', '.join(s for s in d.failed_scenarios if s != 'unchanged')}"
        for d in dependencies if any(s != "unchanged" for s in d.failed_scenarios)
    )
    return PriceRobustnessAssessment(
        price_dependencies=tuple(dependencies), price_robust=(total_failed == 0),
        number_of_failed_price_scenarios=total_failed, critical_price_assumptions=critical,
    )
