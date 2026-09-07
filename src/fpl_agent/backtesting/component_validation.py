"""Real componentwise projection validation (2026-09-07, Phase 7.4 Part 6) -
`harness.py::run_backtest` only ever scores the COMBINED "core FPL points"
prediction (appearance+goals+assists+cards folded into one number), which
can hide a real deficiency in one component behind an average that looks
fine overall. This module scores each real per-90-rate component this
project's live model actually uses (goals/assists/xg/xa via `player_
regression.py::player_shrunk_rates`, minutes via `minutes_distribution.py`)
SEPARATELY, using the identical walk-forward-safe (`as_of_date`) formula
the live path and `harness.py` already trust - never a second, drift-prone
copy of the leakage-safe cutoff logic.

Real, disclosed scope limit: only components this project's live model
actually produces a standalone per-90/probability projection for are
validated here. SHOTS and KEY_PASSES are real Understat inputs but are
never themselves a scored FPL output the live model targets (they feed
INTO the goals/assists rate estimation, not out of it) - validating them
would measure an intermediate, not a decision-relevant prediction, so they
are deliberately not included. CLEAN_SHEETS come from a structurally
different mechanism (Dixon-Coles team-goals-against, not a per-player
rate) - already covered by this project's own existing team-strength
walk-forward work, not duplicated here. SAVES has no dedicated model in
this project at all. BONUS already has its own real componentwise
backtest (`harness.py::score_bonus_regression`, a season-level leave-one-
out holdout - a genuinely different validation shape since no per-match
bonus data exists anywhere) - reported alongside these, not rebuilt.
CAPTAINCY OUTCOME DISTRIBUTIONS is Phase 7.4 Part 7's own scope (P(0)/
P(2+)/P(5+)/P(10+) calibration), not duplicated here either.
"""
import sqlite3
import statistics
from dataclasses import dataclass

from fpl_agent.backtesting import data_fidelity
from fpl_agent.backtesting.harness import _round_start_dates
from fpl_agent.models.expected_points import _MIN_MATCHES_FOR_HIERARCHICAL_PRIOR, _hierarchical_prior_rates
from fpl_agent.models.minutes_distribution import minutes_bucket_probabilities
from fpl_agent.models.player_regression import player_shrunk_rates

_RATE_COMPONENTS = ("goals", "assists", "xg", "xa")


@dataclass(frozen=True)
class ComponentValidationResult:
    stat: str
    season: str
    sample_size: int
    model_mae: float
    model_bias: float  # mean(predicted - actual); positive = model overpredicts
    baseline_mae: float
    baseline_bias: float
    fallback_excluded_count: int  # real matches skipped - see harness.py's own LEAKAGE EXCLUSION note
    # Real, disclosed scope limit (Phase 7.4 Part 12's shared data-
    # confidence contract, `data_fidelity.py`) - a season's real count of
    # player-seasons below VALID confidence. These player-seasons are
    # already structurally invisible to this validation (an unresolved
    # player-season contributes zero rows to `player_match_stats_history`
    # in the first place, so there's nothing for the loop below to skip) -
    # this count exists so the result honestly discloses how much of the
    # real season it could NOT evaluate, rather than reporting a clean MAE
    # over a silently shrunken pool.
    low_confidence_player_seasons: int


def validate_rate_component(conn: sqlite3.Connection, season: str, stat: str) -> ComponentValidationResult:
    """Real walk-forward MAE/bias for one per-90-rate component
    (goals/assists/xg/xa) - the SAME `player_shrunk_rates`/hierarchical-
    prior formula the live model and `harness.py` already trust, scored at
    the raw STAT level (e.g. "predicted 0.3 assists this round") rather
    than converted into FPL points - more directly interpretable, and
    isolates this one component's own error from every other component's."""
    if stat not in _RATE_COMPONENTS:
        raise ValueError(f"unsupported rate component: {stat!r} - expected one of {_RATE_COMPONENTS}")
    starts = _round_start_dates(conn, season)
    if not starts:
        raise ValueError(f"no match_results_history rows for season {season}")
    boundaries = starts + [None]

    model_errors, model_signed, baseline_errors, baseline_signed = [], [], [], []
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
            predicted = shrunk[stat].shrunk_per90 * effective_minutes_fraction
            baseline = shrunk[stat].raw_per90 * effective_minutes_fraction
            actual = row[stat]

            model_signed.append(predicted - actual)
            model_errors.append(abs(predicted - actual))
            baseline_signed.append(baseline - actual)
            baseline_errors.append(abs(baseline - actual))

    return ComponentValidationResult(
        stat=stat, season=season, sample_size=len(model_errors),
        model_mae=round(statistics.mean(model_errors), 4) if model_errors else 0.0,
        model_bias=round(statistics.mean(model_signed), 4) if model_signed else 0.0,
        baseline_mae=round(statistics.mean(baseline_errors), 4) if baseline_errors else 0.0,
        baseline_bias=round(statistics.mean(baseline_signed), 4) if baseline_signed else 0.0,
        fallback_excluded_count=fallback_excluded,
        low_confidence_player_seasons=data_fidelity.low_confidence_player_season_count(conn, season),
    )


@dataclass(frozen=True)
class MinutesValidationResult:
    season: str
    sample_size: int
    model_mae: float
    model_bias: float
    fallback_excluded_count: int
    low_confidence_player_seasons: int  # see ComponentValidationResult's own field docstring


def validate_minutes_component(conn: sqlite3.Connection, season: str) -> MinutesValidationResult:
    """Real walk-forward MAE/bias for expected MINUTES specifically - a
    genuinely different mechanism from the rate components above (a
    3-bucket probability distribution, not a per-90 rate), reusing the
    SAME `(p_partial/3 + p_full) * 90` expected-minutes formula the live
    model's own `effective_minutes_fraction` convention already
    establishes everywhere else in this project."""
    starts = _round_start_dates(conn, season)
    if not starts:
        raise ValueError(f"no match_results_history rows for season {season}")
    boundaries = starts + [None]

    errors, signed = [], []
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
            minutes_probs = minutes_bucket_probabilities(conn, row["player_id"], season, as_of_date=round_start)
            if minutes_probs.source != "empirical":
                fallback_excluded += 1
                continue
            predicted_minutes = (minutes_probs.p_partial / 3 + minutes_probs.p_full) * 90
            actual_minutes = row["minutes"]
            signed.append(predicted_minutes - actual_minutes)
            errors.append(abs(predicted_minutes - actual_minutes))

    return MinutesValidationResult(
        season=season, sample_size=len(errors),
        model_mae=round(statistics.mean(errors), 4) if errors else 0.0,
        model_bias=round(statistics.mean(signed), 4) if signed else 0.0,
        fallback_excluded_count=fallback_excluded,
        low_confidence_player_seasons=data_fidelity.low_confidence_player_season_count(conn, season),
    )
