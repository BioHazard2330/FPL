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
"""
import sqlite3
from dataclasses import dataclass

from fpl_agent.models.expected_minutes import expected_minutes

_MIN_MATCHES_FOR_EMPIRICAL = 4


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
        zero = sum(1 for r in rows if r["minutes"] == 0) / n
        partial = sum(1 for r in rows if 0 < r["minutes"] < 60) / n
        full = sum(1 for r in rows if r["minutes"] >= 60) / n
        return MinutesBucketProbabilities(zero, partial, full, "empirical")

    em = expected_minutes(conn, player_id)
    nonzero_fraction = min(em.expected_minutes / 90, 1.0)
    full = nonzero_fraction * 0.85
    partial = nonzero_fraction * 0.15
    zero = max(0.0, 1.0 - full - partial)
    return MinutesBucketProbabilities(zero, partial, full, "fallback_prior")


def expected_appearance_points(probs: MinutesBucketProbabilities) -> float:
    return probs.p_partial * 1.0 + probs.p_full * 2.0
