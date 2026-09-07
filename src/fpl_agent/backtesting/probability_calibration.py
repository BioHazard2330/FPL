"""Real probability-calibration validation (2026-09-07, Phase 7.4 Part 7) -
Phase 7.3 added `OutcomeProbabilities` (P(0)/P(2+)/P(5+)/P(10+) FPL points),
read off `expected_points()`'s own Dixon-Coles-correlated Monte Carlo trials.
The real question this module answers: does a probability read off the
model's own rate assumption actually match reality, or is it decorative?

Real, disclosed scope limit: this does NOT replay the full live Monte Carlo
pipeline (`_sampled_floor_ceiling` - Dixon-Coles team-strength fit + odds
blend + correlated per-trial scorelines) historically. That pipeline needs a
real forward-looking FIXTURE (opponent, home/away) to draw a scoreline from;
`season_backtest.py`'s walk-forward replay only has real match RESULTS, not
a reconstructed historical fixture list with real team-strength ratings as
of each round - building that is a real, separate, much larger engineering
lift (a full historical Dixon-Coles refit per round, and reconstructing
'who played whom' from match_results_history) and is not attempted here.

Instead this validates the ONE real, checkable assumption every version of
this project's goal-probability logic - live or historical - shares: goals
are modeled as Poisson-distributed with the player's own predicted per-90
rate as the mean (the same assumption `scenario_sampling.py`'s per-trial
binomial draw and `expected_points.py`'s Monte Carlo both build on, just
without this module's real, direct binning-and-frequency check applied to
either of them before now). A real Poisson P(X>=1)/P(X>=2) is computed
directly from the SAME real walk-forward-safe predicted rate `component_
validation.py` already validates (no new prediction machinery), then binned
by predicted probability decile and compared against the REAL realized
frequency in that bin - a genuine calibration curve, plus a real Brier
score. If this real, simpler proxy is well-calibrated, the live Monte
Carlo's OWN goal draws (an even more granular per-trial version of the
identical Poisson assumption) inherit that trustworthiness for the
"how often does the player actually get 1+/2+ goals" question specifically
- the live simulation's REAL value-add over this proxy is combining that
per-player draw with a correlated TEAM scoreline and bonus/assists/cards
in the same trial, not a materially different goal-probability model.
"""
import math
import sqlite3
import statistics
from dataclasses import dataclass

from fpl_agent.backtesting import data_fidelity
from fpl_agent.backtesting.harness import _round_start_dates
from fpl_agent.models.expected_points import _MIN_MATCHES_FOR_HIERARCHICAL_PRIOR, _hierarchical_prior_rates
from fpl_agent.models.minutes_distribution import minutes_bucket_probabilities
from fpl_agent.models.player_regression import player_shrunk_rates

_N_BINS = 5  # quintiles - a real, disclosed choice; finer bins would starve for real sample size


@dataclass(frozen=True)
class CalibrationBin:
    bin_index: int
    predicted_mean: float  # real mean predicted probability of players/rounds landing in this bin
    realized_frequency: float  # real fraction of them that actually crossed the threshold
    sample_size: int


@dataclass(frozen=True)
class ProbabilityCalibrationResult:
    season: str
    threshold: int  # "1+" or "2+" goals
    sample_size: int
    brier_score: float  # mean((predicted - actual)^2); 0 = perfect, 0.25 = a coin-flip predictor's ceiling for a 50/50 base rate
    bins: tuple[CalibrationBin, ...]
    fallback_excluded_count: int
    low_confidence_player_seasons: int  # see component_validation.py's ComponentValidationResult field docstring


def _poisson_prob_at_least(lam: float, k: int) -> float:
    """P(X >= k) for X ~ Poisson(lam), k in {1, 2} - the two real thresholds
    this module checks. Closed-form, no scipy dependency."""
    if lam <= 0:
        return 0.0
    p0 = math.exp(-lam)
    if k == 1:
        return 1.0 - p0
    if k == 2:
        return 1.0 - p0 - lam * p0
    raise ValueError(f"unsupported threshold k={k!r} - only 1 or 2 implemented")


def validate_goal_probability_calibration(
    conn: sqlite3.Connection, season: str, threshold: int = 1,
) -> ProbabilityCalibrationResult:
    starts = _round_start_dates(conn, season)
    if not starts:
        raise ValueError(f"no match_results_history rows for season {season}")
    boundaries = starts + [None]

    predicted_probs: list[float] = []
    actuals: list[int] = []
    fallback_excluded = 0

    for i in range(len(starts)):
        round_start, round_end = boundaries[i], boundaries[i + 1]
        clause = "AND match_date < ?" if round_end else ""
        params = (season, round_start) + ((round_end,) if round_end else ())
        rows = conn.execute(
            f"SELECT * FROM player_match_stats_history WHERE season=? AND match_date >= ? {clause}", params,
        ).fetchall()

        for row in rows:
            if row["player_id"] is None:
                continue
            player_id = row["player_id"]
            minutes_probs = minutes_bucket_probabilities(conn, player_id, season, as_of_date=round_start)
            if minutes_probs.source != "empirical":
                fallback_excluded += 1
                continue

            unshrunk = player_shrunk_rates(conn, player_id, season, as_of_date=round_start)
            if 0 < unshrunk["goals"].matches_played < _MIN_MATCHES_FOR_HIERARCHICAL_PRIOR:
                priors = _hierarchical_prior_rates(conn, player_id, season, as_of_date=round_start)
                shrunk = player_shrunk_rates(conn, player_id, season, as_of_date=round_start, prior_overrides=priors)
            else:
                shrunk = unshrunk

            effective_minutes_fraction = minutes_probs.p_partial / 3 + minutes_probs.p_full
            lam = shrunk["goals"].shrunk_per90 * effective_minutes_fraction
            predicted_probs.append(_poisson_prob_at_least(lam, threshold))
            actuals.append(1 if row["goals"] >= threshold else 0)

    low_confidence = data_fidelity.low_confidence_player_season_count(conn, season)
    if not predicted_probs:
        return ProbabilityCalibrationResult(
            season=season, threshold=threshold, sample_size=0, brier_score=0.0, bins=(),
            fallback_excluded_count=fallback_excluded, low_confidence_player_seasons=low_confidence,
        )

    brier = statistics.mean((p - a) ** 2 for p, a in zip(predicted_probs, actuals, strict=True))

    order = sorted(range(len(predicted_probs)), key=lambda idx: predicted_probs[idx])
    bin_size = max(1, len(order) // _N_BINS)
    bins = []
    for b in range(_N_BINS):
        start_idx = b * bin_size
        end_idx = (b + 1) * bin_size if b < _N_BINS - 1 else len(order)
        idxs = order[start_idx:end_idx]
        if not idxs:
            continue
        bin_predicted = [predicted_probs[j] for j in idxs]
        bin_actual = [actuals[j] for j in idxs]
        bins.append(CalibrationBin(
            bin_index=b, predicted_mean=round(statistics.mean(bin_predicted), 4),
            realized_frequency=round(statistics.mean(bin_actual), 4), sample_size=len(idxs),
        ))

    return ProbabilityCalibrationResult(
        season=season, threshold=threshold, sample_size=len(predicted_probs),
        brier_score=round(brier, 4), bins=tuple(bins), fallback_excluded_count=fallback_excluded,
        low_confidence_player_seasons=low_confidence,
    )
