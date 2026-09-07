"""Real minutes-model segment audit (2026-09-07, Phase 7.4 Part 8) - Phase
7.3 already fixed a real, measured tier-conditioned shrinkage bug (rotation/
fringe players had their minutes pulled toward a starter-dominated blanket
prior). This module goes deeper: segments each real walk-forward-scored
player-round by the REAL situational context the spec asks for, derived
directly from `player_match_stats_history`'s own real match-date sequence -
never a second, invented signal.

Real, disclosed scope limits (Part 8's own segment list vs what this
project's real data can actually support):
- ESTABLISHED / ROTATION / SUBSTITUTE: derived from the real trailing-5-
  match median minutes strictly before the scored round - the same real
  full-match-rate concept `minutes_distribution.py`'s own tier-conditioning
  fix already uses, applied here as a walk-forward-safe SEGMENT label
  rather than a shrinkage-prior selector.
- NEW_SIGNING_OR_FIRST_APPEARANCE: this player's first-ever real match row
  for this season - genuinely the same observable signal Part 8 lists as
  two categories ("new signing" and "first appearance for club"); this
  project has no historical player-transfer-date table to distinguish a
  genuine new arrival from a academy player's senior debut, so both
  collapse into one honestly-labelled segment.
- RETURNING_AFTER_ABSENCE: a real gap of >= `_ABSENCE_GAP_DAYS` since this
  player's own last real match appearance. Part 8 separately lists
  "injury return" and "suspension return" - this project has no historical
  injury/suspension record for past seasons (`players.status`/`.news` are
  LIVE-only fields, never backfilled), so the two cannot be told apart from
  data alone and are honestly merged into one segment, disclosed here
  rather than guessed at.
- CONGESTED_SCHEDULE: this player's own TEAM played another real match
  within `_CONGESTION_GAP_DAYS` before this one (derived from
  `match_results_history`, real fixture dates - never invented).
- MANAGER_OR_TACTICAL_CHANGE: Part 8's own explicit ask, NOT built - this
  project's `change_events` table (the only real source of tactical/
  manager-change signals) is confirmed live-only (earliest real row
  2026-08-12, the current season) - zero historical rows exist for any
  past season this backtest can replay. Reported as a real, structural
  data-availability gap, not silently skipped without disclosure.
- DEFAULT: none of the above triggered - a genuinely unremarkable round for
  an already-established-pattern player (folds into ESTABLISHED/ROTATION/
  SUBSTITUTE by the trailing-median rule above; DEFAULT itself never
  fires standalone)."""
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import date

from fpl_agent.backtesting import data_fidelity
from fpl_agent.models.minutes_distribution import _is_returning_after_absence, minutes_bucket_probabilities

ESTABLISHED = "ESTABLISHED_STARTER"
ROTATION = "ROTATION_PLAYER"
SUBSTITUTE = "SUBSTITUTE"
NEW_OR_FIRST_APPEARANCE = "NEW_SIGNING_OR_FIRST_APPEARANCE"
RETURNING_AFTER_ABSENCE = "RETURNING_AFTER_ABSENCE"
CONGESTED_SCHEDULE = "CONGESTED_SCHEDULE"
MANAGER_TACTICAL_CHANGE_NOT_AVAILABLE = "MANAGER_OR_TACTICAL_CHANGE_DATA_NOT_AVAILABLE"

_CONGESTION_GAP_DAYS = 4  # two real matches inside a 4-day window - a genuine top-flight congestion signal (midweek + weekend)
_TRAILING_WINDOW = 5


def _parse_date(d: str) -> date:
    return date.fromisoformat(d[:10])


def classify_round_segment(
    conn: sqlite3.Connection, player_id: int, team_id: int, season: str, as_of_date: str,
) -> str:
    """Real, walk-forward-safe segment label for the round starting
    `as_of_date` - only ever reads rows strictly before it, matching every
    other real leakage-safe read in this project."""
    prior_rows = conn.execute(
        "SELECT match_date, minutes FROM player_match_stats_history "
        "WHERE player_id=? AND season=? AND match_date < ? ORDER BY match_date",
        (player_id, season, as_of_date),
    ).fetchall()
    if not prior_rows:
        return NEW_OR_FIRST_APPEARANCE

    # Real, shared definition (Phase 7.4 Part 8/11) - the SAME check the
    # live minutes model itself now uses to apply a real, measured fix
    # (`models/minutes_distribution.py::_is_returning_after_absence`) -
    # never a second, independently-tuned gap threshold.
    if _is_returning_after_absence(conn, player_id, season, as_of_date):
        return RETURNING_AFTER_ABSENCE

    team_match = conn.execute(
        "SELECT match_date FROM match_results_history WHERE season=? AND match_date < ? "
        "AND (home_team_id=? OR away_team_id=?) ORDER BY match_date DESC LIMIT 1",
        (season, as_of_date, team_id, team_id),
    ).fetchone()
    if team_match is not None:
        team_gap = (_parse_date(as_of_date) - _parse_date(team_match["match_date"])).days
        if 0 < team_gap <= _CONGESTION_GAP_DAYS:
            return CONGESTED_SCHEDULE

    trailing = prior_rows[-_TRAILING_WINDOW:]
    median_minutes = statistics.median(r["minutes"] for r in trailing)
    if median_minutes >= 60:
        return ESTABLISHED
    if median_minutes >= 20:
        return ROTATION
    return SUBSTITUTE


@dataclass(frozen=True)
class SegmentMinutesResult:
    segment: str
    season: str
    sample_size: int
    model_mae: float
    model_bias: float  # mean(predicted - actual); positive = overpredicts real minutes
    fallback_excluded_count: int
    # Season-wide, not per-segment (a season-level scope limit repeated
    # identically across every segment's own result - see
    # `component_validation.py`'s `ComponentValidationResult` field
    # docstring for what this counts and why).
    low_confidence_player_seasons: int


def audit_minutes_by_segment(conn: sqlite3.Connection, season: str) -> dict[str, SegmentMinutesResult]:
    """Real walk-forward minutes MAE/bias, one result PER real segment -
    reuses the exact same predicted-minutes formula `component_validation.
    validate_minutes_component` already validates in aggregate, just
    grouped by the real situational context above instead of pooled."""
    from fpl_agent.backtesting.harness import _round_start_dates

    starts = _round_start_dates(conn, season)
    if not starts:
        raise ValueError(f"no match_results_history rows for season {season}")
    boundaries = starts + [None]

    by_segment: dict[str, list[tuple[float, float]]] = {}  # segment -> [(predicted, actual), ...]
    fallback_excluded_by_segment: dict[str, int] = {}

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
            segment = classify_round_segment(conn, player_id, row["market_team_id"], season, round_start)

            minutes_probs = minutes_bucket_probabilities(conn, player_id, season, as_of_date=round_start)
            if minutes_probs.source != "empirical":
                fallback_excluded_by_segment[segment] = fallback_excluded_by_segment.get(segment, 0) + 1
                continue
            predicted_minutes = (minutes_probs.p_partial / 3 + minutes_probs.p_full) * 90
            by_segment.setdefault(segment, []).append((predicted_minutes, row["minutes"]))

    low_confidence = data_fidelity.low_confidence_player_season_count(conn, season)
    results = {}
    for segment, pairs in by_segment.items():
        errors = [abs(p - a) for p, a in pairs]
        signed = [p - a for p, a in pairs]
        results[segment] = SegmentMinutesResult(
            segment=segment, season=season, sample_size=len(pairs),
            model_mae=round(statistics.mean(errors), 2), model_bias=round(statistics.mean(signed), 2),
            fallback_excluded_count=fallback_excluded_by_segment.get(segment, 0),
            low_confidence_player_seasons=low_confidence,
        )
    return results
