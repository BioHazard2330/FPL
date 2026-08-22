"""Shared trend classification over match_observations (Pillar 4, Team/Player
Intelligence pass, 2026-08-22). One real, deterministic rule, used by both
`player_intelligence.py` and `team_intelligence.py` so a player's ROLE trend
and a team's TEAM_ATTACK trend are judged by the exact same standard - never
two subtly different heuristics for what should be the same concept.

Real, disclosed rule (spec section 16/17's own "do not declare persistent
trends from tiny samples" warning, taken literally): a signal needs the two
MOST RECENT observations to agree before it's called anything but brand new,
and a third, older observation that disagrees downgrades it to NOISE rather
than letting two lucky matches in a row look more settled than they are.
"""
from dataclasses import dataclass
from typing import Literal

TrendLabel = Literal["NEW_SIGNAL", "PERSISTENT_TREND", "REVERSAL", "NOISE"]


@dataclass(frozen=True)
class SignalTrend:
    signal: str  # the real fpl_signal value (ROLE, MINUTES, CREATION, ...)
    label: TrendLabel
    current_direction: str  # the most recent fpl_direction
    sample_size: int  # how many real observations of this signal this trend was computed from
    history: list[str]  # directions, most-recent-first, capped to the lookback window


def classify_direction_history(directions_most_recent_first: list[str]) -> TrendLabel:
    """`directions_most_recent_first` is a list of real fpl_direction values
    from match_observations, most recent match first, already capped to the
    caller's lookback window. Never called with an empty list (the caller's
    job to skip a signal with zero evidence, not this function's)."""
    if len(directions_most_recent_first) == 1:
        return "NEW_SIGNAL"
    if directions_most_recent_first[0] != directions_most_recent_first[1]:
        return "REVERSAL"
    if len(directions_most_recent_first) >= 3 and directions_most_recent_first[2] != directions_most_recent_first[0]:
        return "NOISE"
    return "PERSISTENT_TREND"


def signal_trends_for_subject(
    conn, subject_type: str, subject_id: int, lookback: int = 5,
) -> list[SignalTrend]:
    """Real per-signal trend, grouped by the real fpl_signal value already
    stored on every FULL_TIME-phase observation (HALFTIME rows are
    deliberately excluded - provisional evidence from an unfinished match
    should never seed a trend). Ordered by the real match kickoff time, not
    insertion order (a re-run/re-analysis of an older match must not be
    mistaken for a newer one)."""
    rows = conn.execute(
        "SELECT o.fpl_signal, o.fpl_direction, mi.kickoff_utc "
        "FROM match_observations o JOIN match_intelligence mi ON mi.id = o.match_id "
        "WHERE o.subject_type=? AND o.subject_id=? AND o.phase='FULL_TIME' "
        "AND o.fpl_signal IS NOT NULL AND o.fpl_direction IS NOT NULL "
        "ORDER BY mi.kickoff_utc DESC",
        (subject_type, subject_id),
    ).fetchall()

    by_signal: dict[str, list[str]] = {}
    for r in rows:
        by_signal.setdefault(r["fpl_signal"], []).append(r["fpl_direction"])

    trends = []
    for signal, directions in by_signal.items():
        window = directions[:lookback]
        trends.append(SignalTrend(
            signal=signal, label=classify_direction_history(window),
            current_direction=window[0], sample_size=len(window), history=window,
        ))
    trends.sort(key=lambda t: t.signal)
    return trends
