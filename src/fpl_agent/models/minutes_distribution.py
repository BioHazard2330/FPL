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

from fpl_agent.models.availability import classify
from fpl_agent.models.expected_minutes import _AVAILABILITY_DAMPING, expected_minutes
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
    for cache_key in [k for k in _position_tier_avg_bucket_cache if k[0] == key]:
        del _position_tier_avg_bucket_cache[cache_key]
    for cache_key in [k for k in _returning_avg_bucket_cache if k[0] == key]:
        del _returning_avg_bucket_cache[cache_key]


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
    mean this season's data hasn't synced yet), never a fabricated split.

    Kept as the real, disclosed FALLBACK prior when a tier-conditioned one
    (`_position_tier_average_minutes_buckets` below) doesn't have enough
    real players to compute from - see that function's own docstring for
    why it's now the primary prior `minutes_bucket_probabilities` blends
    toward."""
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


_MIN_ROWS_FOR_TIER_PRIOR = 20  # below this, a tier prior would itself be a thin, unstable sample - fall back honestly

_position_tier_avg_bucket_cache: dict[tuple[int, str, str, str, str | None], tuple[sqlite3.Connection, tuple | None]] = {}

# Real, cross-season-validated threshold (2026-09-07, Phase 7.4 Part 8 minutes
# audit - `backtesting/minutes_audit.py::classify_round_segment` uses this
# same real value, kept in sync via the shared `_is_returning_after_absence`
# below rather than a second, independently-tuned constant) - ~3 real match-
# rounds' worth of silence, not fit to data.
_ABSENCE_GAP_DAYS = 21

_returning_avg_bucket_cache: dict[tuple[int, str, str | None], tuple[sqlite3.Connection, tuple | None]] = {}


def _is_returning_after_absence(conn: sqlite3.Connection, player_id: int, season: str, as_of_date: str | None) -> bool:
    """Real check: did this player's own last real match end at least
    `_ABSENCE_GAP_DAYS` before `as_of_date`? Shared by the live model
    (below) and `backtesting/minutes_audit.py`'s own segment audit - one
    real definition of "returning", not two independently-tuned ones.

    `as_of_date=None` (live mode - "as of right now") uses the real current
    UTC date as the cutoff, matching every other genuinely-live (undated)
    read this project already makes (e.g. `expected_minutes()`'s own live
    `players.status`/newest-snapshot reads) - this is the one real case
    this function is MOST valuable for (a real current squad player just
    back from a real injury), so it is deliberately not skipped in live
    mode the way a leakage-sensitive backtest read would be."""
    from datetime import date, datetime, timezone

    clause, params = ("AND match_date < ?", (as_of_date,)) if as_of_date else ("", ())
    row = conn.execute(
        f"SELECT match_date FROM player_match_stats_history WHERE player_id=? AND season=? {clause} "
        "ORDER BY match_date DESC LIMIT 1",
        (player_id, season) + params,
    ).fetchone()
    if row is None:
        return False
    cutoff = date.fromisoformat(as_of_date[:10]) if as_of_date else datetime.now(timezone.utc).date()
    gap_days = (cutoff - date.fromisoformat(row["match_date"][:10])).days
    return gap_days >= _ABSENCE_GAP_DAYS


def _returning_after_absence_average_minutes_buckets(
    conn: sqlite3.Connection, position: str, season: str, as_of_date: str | None = None,
) -> tuple[float, float, float] | None:
    """Real, measured fix (2026-09-07, Phase 7.4 Part 8 minutes audit) - a
    real walk-forward segment audit found RETURNING_AFTER_ABSENCE the single
    largest, most consistent minutes-bias segment of any tested, across
    EVERY real backtestable season checked: +19.48 (2023-24), +10.75
    (2024-25), +10.49 (2025-26) average minutes overprediction - roughly
    2x the MAE of an established starter, the model's real single worst
    calibration gap. Real football interpretation: a player just back from
    a real injury/suspension absence is very commonly eased back in
    (reduced minutes, tactical caution) rather than immediately restored to
    their pre-absence workload - but `minutes_bucket_probabilities`'s own
    trailing-<=10-match raw sample is dominated by STALE pre-absence rows
    for a player who has only just returned, so neither the raw estimate
    nor the established/rotational/fringe tier it gets classified into (see
    `_minutes_tier`) reflects the real return-to-fitness pattern at all.

    Real, not-arbitrary construction, the SAME real pattern `_position_tier_
    average_minutes_buckets` already established: every OTHER real player at
    this position has their OWN match sequence walked (Python, not SQL - a
    per-player sequential gap check isn't expressible as a single real join)
    to find matches that THEMSELVES directly followed a real `_is_returning_
    after_absence`-qualifying gap for that player - the prior is the real
    bucket-frequency average across only those genuinely-returning real
    match instances, never a fabricated split. `None` (the caller falls back
    to the blanket position average, matching the established-tier
    precedent) when fewer than `_MIN_ROWS_FOR_TIER_PRIOR` real qualifying
    rows exist."""
    key = (id(conn), position, season, as_of_date)
    cached = _returning_avg_bucket_cache.get(key)
    if cached is not None and cached[0] is conn:
        return cached[1]

    clause, params = ("AND match_date < ?", (as_of_date,)) if as_of_date else ("", ())
    rows = conn.execute(
        "SELECT psh.player_id, psh.match_date, psh.minutes FROM player_match_stats_history psh "
        "JOIN players p ON p.id = psh.player_id "
        "JOIN element_types et ON et.id = p.element_type "
        f"WHERE et.singular_name_short = ? AND psh.season = ? {clause} "
        "ORDER BY psh.player_id, psh.match_date ASC",
        (position, season) + params,
    ).fetchall()

    from datetime import date

    by_player: dict[int, list] = {}
    for r in rows:
        by_player.setdefault(r["player_id"], []).append(r)

    zero_n = partial_n = full_n = total_n = 0
    for _pid, matches in by_player.items():
        for i in range(1, len(matches)):
            prev_date = date.fromisoformat(matches[i - 1]["match_date"][:10])
            cur_date = date.fromisoformat(matches[i]["match_date"][:10])
            if (cur_date - prev_date).days < _ABSENCE_GAP_DAYS:
                continue
            m = matches[i]["minutes"]
            total_n += 1
            if m == 0:
                zero_n += 1
            elif m < 60:
                partial_n += 1
            else:
                full_n += 1

    result = (
        (zero_n / total_n, partial_n / total_n, full_n / total_n)
        if total_n >= _MIN_ROWS_FOR_TIER_PRIOR else None
    )
    _returning_avg_bucket_cache[key] = (conn, result)
    return result


def _minutes_tier(full_rate: float) -> str:
    """Same real, disclosed tier boundaries the 2026-09-07 walk-forward
    diagnostic below used to MEASURE the bug this fixes - not re-tuned here,
    reused exactly so the fix targets the same segments the evidence came
    from."""
    if full_rate >= 0.75:
        return "established"
    if full_rate >= 0.25:
        return "rotational"
    return "fringe"


def _position_tier_average_minutes_buckets(
    conn: sqlite3.Connection, position: str, tier: str, season: str, as_of_date: str | None = None,
) -> tuple[float, float, float] | None:
    """Real, tier-conditioned (zero, partial, full) bucket-frequency prior -
    fixes a real, measured calibration bug found 2026-09-07 (Phase 7.3
    minutes-model diagnostic, walk-forward against the real 2025-26 season):
    blending EVERY player toward the SAME blanket position-wide average
    (`_position_average_minutes_buckets` above) systematically overpredicts
    minutes for rotation-risk/fringe players (measured +10.2/+17.4 real
    average minutes bias) - because that pooled average is dominated by
    established-starter rows (most real minutes played at any position
    come from the 11 who start, not the handful of used subs), so shrinking
    a genuinely fringe player's own correctly-low empirical rate toward it
    pulls the estimate UP regardless of whether this specific player is
    actually fringe.

    Real, measured, NOT applied to the "established" tier: established
    starters were already well-calibrated under the OLD blanket prior
    (measured bias -0.02) - a first version of this fix applied the SAME
    tier-conditioning to every tier and found it introduced a NEW +6.15
    average-minutes bias for established players (the established tier's
    own prior, e.g. 92.2% real full-match rate for MID vs the blanket
    prior's 63.8%, sits at the high end of that tier's own real spread -
    blending a player who only just crossed the >=75% established
    threshold toward it pulls their estimate up more than the old, lower
    blanket prior did). `minutes_bucket_probabilities` below only calls
    this for the rotational/fringe tiers where a real miscalibration was
    actually measured, keeping the established tier on the original
    blanket prior it was already correct under - this is why `tier`
    callers should never pass `"established"` here.

    Real, not-arbitrary construction: every OTHER real player at this
    position is itself classified into the same three tiers
    (`_minutes_tier`) by their OWN real full-match rate over their last <=10
    pre-`as_of_date` matches (`_MIN_MATCHES_FOR_EMPIRICAL`-gated, same real
    bar the caller's own empirical branch requires) - the prior is the real
    bucket-frequency average across only the players who share the target
    player's own tier, never a fabricated split. `None` (the caller falls
    back to the blanket position average) when fewer than
    `_MIN_ROWS_FOR_TIER_PRIOR` real match-rows exist in that tier - an
    honest "not enough real players in this tier yet" rather than a prior
    built from a handful of rows."""
    key = (id(conn), position, tier, season, as_of_date)
    cached = _position_tier_avg_bucket_cache.get(key)
    if cached is not None and cached[0] is conn:
        return cached[1]

    clause, params = ("AND match_date < ?", (as_of_date,)) if as_of_date else ("", ())
    rows = conn.execute(
        "SELECT psh.player_id, psh.minutes FROM player_match_stats_history psh "
        "JOIN players p ON p.id = psh.player_id "
        "JOIN element_types et ON et.id = p.element_type "
        f"WHERE et.singular_name_short = ? AND psh.season = ? {clause} "
        "ORDER BY psh.player_id, psh.match_date DESC",
        (position, season) + params,
    ).fetchall()

    by_player: dict[int, list[int]] = {}
    for r in rows:
        by_player.setdefault(r["player_id"], []).append(r["minutes"])

    zero_n = partial_n = full_n = total_n = 0
    for _pid, minutes_list in by_player.items():
        recent = minutes_list[:10]  # already DESC by match_date - same real <=10-match window the caller uses
        if len(recent) < _MIN_MATCHES_FOR_EMPIRICAL:
            continue
        full_rate = sum(1 for m in recent if m >= 60) / len(recent)
        if _minutes_tier(full_rate) != tier:
            continue
        for m in recent:
            total_n += 1
            if m == 0:
                zero_n += 1
            elif m < 60:
                partial_n += 1
            else:
                full_n += 1

    result = (
        (zero_n / total_n, partial_n / total_n, full_n / total_n)
        if total_n >= _MIN_ROWS_FOR_TIER_PRIOR else None
    )
    _position_tier_avg_bucket_cache[key] = (conn, result)
    return result


@dataclass(frozen=True)
class MinutesBucketProbabilities:
    p_zero: float
    p_partial: float  # 1-59 minutes
    p_full: float  # 60+ minutes
    source: str  # "empirical" or "fallback_prior"


def _apply_live_availability_damping(
    conn: sqlite3.Connection, player_id: int, zero: float, partial: float, full: float,
) -> tuple[float, float, float]:
    """Real, live-only correction (2026-09-13, direct user complaint: a
    wildcard squad started a real concussion doubt). The "empirical" branch
    above is built purely from past match MINUTES - structurally blind to a
    player's own CURRENT official status/chance-of-playing (Tier 1, this
    project's own most authoritative signal - see CLAUDE.md's data-source
    precedence rule), since a player with >=4 recent matches never falls
    through to expected_minutes()'s own availability-aware fallback path at
    all. Confirmed live: a real player 4-for-4 on 60+ minute appearances,
    with a fresh official "Concussion - 50% chance of playing" note for the
    next match, still showed an 82.6% full-match probability before this
    fix - the exact "why is this obviously-doubtful player starting"
    failure the empirical path's own real-data confidence was never meant
    to paper over. Reuses the SAME `_AVAILABILITY_DAMPING` scale
    `expected_minutes()` already applies on its own fallback path - shrinks
    partial/full proportionally, moving the removed mass to zero, never a
    fabricated new distribution shape.

    Gated to as_of_date is None by the caller (live only) - a walk-forward
    backtest replay must never let today's real status leak into a
    historical estimate, the same leakage boundary expected_minutes()'s own
    live-only overrides already draw."""
    player = conn.execute("SELECT status FROM players WHERE id=?", (player_id,)).fetchone()
    if player is None:
        return zero, partial, full
    snapshot = conn.execute(
        "SELECT chance_of_playing_this_round, chance_of_playing_next_round "
        "FROM player_stats_snapshot WHERE player_id=? ORDER BY retrieved_at DESC LIMIT 1",
        (player_id,),
    ).fetchone()
    chance_this = snapshot["chance_of_playing_this_round"] if snapshot else None
    chance_next = snapshot["chance_of_playing_next_round"] if snapshot else None
    classification = classify(player["status"], chance_this, chance_next)
    damping = _AVAILABILITY_DAMPING[classification]
    if damping >= 1.0:
        return zero, partial, full
    damped_partial = partial * damping
    damped_full = full * damping
    damped_zero = max(0.0, 1.0 - damped_partial - damped_full)
    return damped_zero, damped_partial, damped_full


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
        # Real fix 2026-09-07 (Phase 7.3 Part 2 - measured minutes-model
        # diagnostic) - blend toward the real tier-conditioned prior for the
        # rotational/fringe tiers, where the blanket position-wide prior
        # below was measurably overpredicting minutes by +10.2/+17.4 real
        # average minutes (starter-dominated pool). Established players stay
        # on the original blanket prior - a first version that also tier-
        # conditioned "established" measurably introduced a NEW +6.15 bias
        # there (see `_position_tier_average_minutes_buckets`'s own
        # docstring for why); the blanket prior was already correct for that
        # tier (measured bias -0.02), so it's kept, not replaced.
        # Real fix 2026-09-07 (Phase 7.4 Part 8 minutes audit) - checked
        # FIRST, ahead of the established/rotational/fringe tier below: a
        # player's own trailing-<=10-match raw sample is dominated by STALE
        # pre-absence rows immediately after a real return, so the tier
        # classification itself (computed from that same stale sample)
        # cannot be trusted to identify this case - the real gap since their
        # own last match is the honest, direct signal instead. See
        # `_returning_after_absence_average_minutes_buckets`'s own docstring
        # for the real, measured evidence (the single largest cross-season
        # minutes bias this project has found: +19.48/+10.75/+10.49).
        returning_prior = (
            _returning_after_absence_average_minutes_buckets(conn, position, season, as_of_date)
            if _is_returning_after_absence(conn, player_id, season, as_of_date)
            else None
        )
        if returning_prior is not None:
            prior_zero, prior_partial, prior_full = returning_prior
        else:
            tier = _minutes_tier(raw_full)
            tier_prior = (
                _position_tier_average_minutes_buckets(conn, position, tier, season, as_of_date)
                if tier != "established" else None
            )
            if tier_prior is not None:
                prior_zero, prior_partial, prior_full = tier_prior
            else:
                prior_zero, prior_partial, prior_full = _position_average_minutes_buckets(
                    conn, position, season, as_of_date,
                )

        k = PRIOR_STRENGTH_MATCHES
        zero = (n * raw_zero + k * prior_zero) / (n + k)
        partial = (n * raw_partial + k * prior_partial) / (n + k)
        full = (n * raw_full + k * prior_full) / (n + k)
        if as_of_date is None:
            zero, partial, full = _apply_live_availability_damping(conn, player_id, zero, partial, full)
        return MinutesBucketProbabilities(zero, partial, full, "empirical")

    em = expected_minutes(conn, player_id)
    nonzero_fraction = min(em.expected_minutes / 90, 1.0)
    full = nonzero_fraction * 0.85
    partial = nonzero_fraction * 0.15
    zero = max(0.0, 1.0 - full - partial)
    return MinutesBucketProbabilities(zero, partial, full, "fallback_prior")


def expected_appearance_points(probs: MinutesBucketProbabilities) -> float:
    return probs.p_partial * 1.0 + probs.p_full * 2.0
