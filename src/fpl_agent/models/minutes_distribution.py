"""Probability distribution over FPL's actual appearance-points buckets
(0 mins -> 0pts, 1-59 -> 1pt, 60+ -> 2pts), replacing the v1 model's linear
proxy on a single expected-minutes number. Built empirically from recent
match-by-match minutes in player_match_stats_history when enough current-
season matches exist; falls back to the existing expected_minutes() point
estimate (last-season prior blended with availability) otherwise - same
fallback logic v1 already used, just split into a bucket distribution
(0.85/0.15 start-vs-cameo split on the nonzero portion is a documented
heuristic, not fit to data - full/partial splits aren't observable from a
single point estimate).

Real calibration fix (2026-09-02, projection-engine forensic audit):
the "empirical" path used to be a bare raw frequency over the last <=10
matches with ZERO shrinkage - the one rate in this entire model layer that
didn't follow the empirical-Bayes pattern every other rate here uses
(models/player_regression.py::shrink_rate, reused as-is by bonus_regression.py
and defensive_contribution.py - shrink the player's own raw rate toward a
population-level positional average, weighted by real sample size). Walk-
forward calibration against the real 2025-26 season found this raw-frequency
approach materially MISCALIBRATED at both tails: players the model rated at
~10% chance of playing 60+ minutes actually did so ~33% of the time (real,
substantial underestimation of fringe/impact-sub players' true minutes
security), while players rated ~92-93% actually reached 60+ only ~82-94% of
the time (mild overconfidence on nailed starters). A 4-10-match raw frequency
is a genuinely small, high-variance sample - one bad/good match anywhere in
that window swings the estimate by 10-25 percentage points, exactly the kind
of noise shrinkage exists to dampen everywhere else in this codebase.

Fixed by blending the player's own raw bucket frequencies toward a real
POSITION-LEVEL bucket-frequency prior (`_position_average_minutes_buckets`,
same population-prior pattern and as_of_date leakage discipline as
`defensive_contribution.py::position_average_defcon_per90` /
`bonus_regression.py::position_average_bonus_per90`), weighted by
`PRIOR_STRENGTH_MATCHES` (the same real shrinkage-strength constant
`player_regression.py` already establishes project-wide - reused, not
reinvented). Deliberately NOT blended toward the live `expected_minutes()`
point estimate the fallback path below uses - that read is undated/live-only
(see this module's own fallback branch, unchanged), and blending it into the
"empirical" branch would silently leak live state into what the backtest
harness trusts as its one genuinely leakage-free path
(`source == "empirical"` is the harness's own scoring-inclusion gate - see
backtesting/harness.py's module docstring). The positional-average prior
below is itself as_of_date-scoped, so the empirical branch stays leakage-free
end to end.
"""
import sqlite3
from dataclasses import dataclass

from fpl_agent.models.expected_minutes import expected_minutes
from fpl_agent.models.player_regression import PRIOR_STRENGTH_MATCHES

_MIN_MATCHES_FOR_EMPIRICAL = 4

# Real perf gap, same pattern as defensive_contribution.py/bonus_regression.py's
# own population-prior caches: this depends only on (position, season,
# as_of_date), never on which player called it.
_position_avg_bucket_cache: dict[tuple[int, str, str, str | None], tuple[sqlite3.Connection, tuple]] = {}


def invalidate_cache_for_connection(conn: sqlite3.Connection) -> None:
    key = id(conn)
    for cache_key in [k for k in _position_avg_bucket_cache if k[0] == key]:
        del _position_avg_bucket_cache[cache_key]


def _position_average_minutes_buckets(
    conn: sqlite3.Connection, position: str, season: str, as_of_date: str | None = None
) -> tuple[float, float, float]:
    """Real population-level (zero, partial, full) bucket frequencies for
    this position, from every real `player_match_stats_history` row strictly
    before `as_of_date` (or the whole season when `as_of_date` is None,
    live mode) - as_of_date-scoped for the identical leakage-free reason
    `defensive_contribution.py`'s sibling function is. Falls back to a flat
    (0, 0, 1) - i.e. "assume a full match" - only in the genuinely
    unreachable case of zero rows existing for the position at all (would
    mean this season's data hasn't synced yet), never a fabricated split."""
    key = (id(conn), position, season, as_of_date)
    cached = _position_avg_bucket_cache.get(key)
    if cached is not None and cached[0] is conn:
        return cached[1]

    clause, params = ("AND match_date < ?", (as_of_date,)) if as_of_date else ("", ())
    row = conn.execute(
        "SELECT "
        "  SUM(CASE WHEN psh.minutes = 0 THEN 1 ELSE 0 END) AS zero_n, "
        "  SUM(CASE WHEN psh.minutes > 0 AND psh.minutes < 60 THEN 1 ELSE 0 END) AS partial_n, "
        "  SUM(CASE WHEN psh.minutes >= 60 THEN 1 ELSE 0 END) AS full_n, "
        "  COUNT(*) AS total_n "
        "FROM player_match_stats_history psh "
        "JOIN players p ON p.id = psh.player_id "
        "JOIN element_types et ON et.id = p.element_type "
        f"WHERE et.singular_name_short = ? AND psh.season = ? {clause}",
        (position, season) + params,
    ).fetchone()

    total = row["total_n"] or 0
    result = (0.0, 0.0, 1.0) if total == 0 else (
        row["zero_n"] / total, row["partial_n"] / total, row["full_n"] / total,
    )
    _position_avg_bucket_cache[key] = (conn, result)
    return result


@dataclass(frozen=True)
class MinutesBucketProbabilities:
    p_zero: float
    p_partial: float  # 1-59 minutes
    p_full: float  # 60+ minutes
    source: str  # "empirical" or "fallback_prior"


def minutes_bucket_probabilities(
    conn: sqlite3.Connection, player_id: int, season: str, as_of_date: str | None = None
) -> MinutesBucketProbabilities:
    clause, extra = ("AND match_date < ?", (as_of_date,)) if as_of_date else ("", ())
    rows = conn.execute(
        f"SELECT minutes FROM player_match_stats_history WHERE player_id=? AND season=? {clause} "
        "ORDER BY match_date DESC LIMIT 10",
        (player_id, season) + extra,
    ).fetchall()

    if len(rows) >= _MIN_MATCHES_FOR_EMPIRICAL:
        n = len(rows)
        raw_zero = sum(1 for r in rows if r["minutes"] == 0) / n
        raw_partial = sum(1 for r in rows if 0 < r["minutes"] < 60) / n
        raw_full = sum(1 for r in rows if r["minutes"] >= 60) / n

        position = conn.execute(
            "SELECT et.singular_name_short AS position FROM players p "
            "JOIN element_types et ON et.id = p.element_type WHERE p.id=?",
            (player_id,),
        ).fetchone()["position"]
        prior_zero, prior_partial, prior_full = _position_average_minutes_buckets(
            conn, position, season, as_of_date,
        )

        k = PRIOR_STRENGTH_MATCHES
        zero = (n * raw_zero + k * prior_zero) / (n + k)
        partial = (n * raw_partial + k * prior_partial) / (n + k)
        full = (n * raw_full + k * prior_full) / (n + k)
        return MinutesBucketProbabilities(zero, partial, full, "empirical")

    em = expected_minutes(conn, player_id)
    nonzero_fraction = min(em.expected_minutes / 90, 1.0)
    full = nonzero_fraction * 0.85
    partial = nonzero_fraction * 0.15
    zero = max(0.0, 1.0 - full - partial)
    return MinutesBucketProbabilities(zero, partial, full, "fallback_prior")


def expected_appearance_points(probs: MinutesBucketProbabilities) -> float:
    return probs.p_partial * 1.0 + probs.p_full * 2.0
