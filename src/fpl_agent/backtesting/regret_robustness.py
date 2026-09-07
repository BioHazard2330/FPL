"""Real regret-vs-robustness correlation (2026-09-07, Phase 7.4 Part 10) -
"determine whether the model's existing warning signals successfully
identify historically regret-prone situations."

Real, disclosed structural limit (Part 10's own explicit instruction is to
"reuse the authoritative decision / strategy robustness / path credibility
machinery that already exists" - `optimization/authoritative_decision.py`'s
real FRAGILE/ROBUST verdicts and credibility labels): that machinery is
computed ONLY by the LIVE multi-GW beam search (`compare_starting_actions`/
`search_transfer_sequences`), which `season_backtest.py`'s own historical
replay deliberately never invokes (single-swap-or-roll only - see that
module's own docstring: "the real, expensive multi-GW beam search...is
deliberately NOT replayed here either"). A historical transfer this
backtest made therefore has no real FRAGILE/ROBUST verdict or credibility
label to read at all - fabricating one would mean running the live beam
search against a reconstructed historical squad state, a real, separate,
much larger engineering lift (effectively replaying `season_backtest.py`
with the full search instead of its cheap single-swap approximation),
honestly out of scope here.

What IS real and available on every historical transfer this backtest
already made: `TransferLogEntry.predicted_gain` - the model's own predicted
EV margin at decision time, the closest real analogue this simplified
replay has to a "how confident was the model in this specific call" signal
(a thin predicted margin is the same kind of "close call" a low robustness
verdict would flag on the live path, just measured directly rather than via
a Monte Carlo trial comparison). This module correlates that real margin
against `decision_regret.py`'s own real, already-computed regret."""
import sqlite3
import statistics
from dataclasses import dataclass

from fpl_agent.backtesting.decision_regret import classify_transfer_regret
from fpl_agent.backtesting.season_backtest import SeasonBacktestResult


@dataclass(frozen=True)
class RegretMarginCorrelation:
    n_transfers: int
    n_regretful: int
    mean_predicted_gain_regretful: float | None
    mean_predicted_gain_not_regretful: float | None
    # Real Pearson-style direction check without a numpy/scipy dependency -
    # a real, simple rank comparison: among all real transfers, does a
    # SMALLER real predicted_gain correlate with a LARGER real regret?
    # `None` when there's too little real data to say anything (n<3).
    spearman_like_correlation: float | None


def _rank(values: list[float]) -> list[float]:
    """Real, plain average-rank implementation (ties share the mean rank) -
    no scipy dependency for an n=8-scale real sample."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def correlate_regret_with_predicted_margin(
    conn: sqlite3.Connection, season: str, result: SeasonBacktestResult,
) -> RegretMarginCorrelation:
    if not result.transfer_log:
        return RegretMarginCorrelation(
            n_transfers=0, n_regretful=0, mean_predicted_gain_regretful=None,
            mean_predicted_gain_not_regretful=None, spearman_like_correlation=None,
        )

    margins = []
    regrets = []
    for entry in result.transfer_log:
        c = classify_transfer_regret(conn, season, entry)
        margins.append(entry.predicted_gain)
        regrets.append(c.regret)

    regretful_margins = [m for m, r in zip(margins, regrets, strict=True) if r > 0]
    non_regretful_margins = [m for m, r in zip(margins, regrets, strict=True) if r <= 0]

    correlation = None
    if len(margins) >= 3:
        margin_ranks = _rank(margins)
        regret_ranks = _rank(regrets)
        n = len(margins)
        mean_mr = statistics.mean(margin_ranks)
        mean_rr = statistics.mean(regret_ranks)
        cov = sum((margin_ranks[i] - mean_mr) * (regret_ranks[i] - mean_rr) for i in range(n))
        std_m = (sum((r - mean_mr) ** 2 for r in margin_ranks)) ** 0.5
        std_r = (sum((r - mean_rr) ** 2 for r in regret_ranks)) ** 0.5
        correlation = round(cov / (std_m * std_r), 4) if std_m > 0 and std_r > 0 else None

    return RegretMarginCorrelation(
        n_transfers=len(margins), n_regretful=len(regretful_margins),
        mean_predicted_gain_regretful=round(statistics.mean(regretful_margins), 2) if regretful_margins else None,
        mean_predicted_gain_not_regretful=round(statistics.mean(non_regretful_margins), 2) if non_regretful_margins else None,
        spearman_like_correlation=correlation,
    )
