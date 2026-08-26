"""Value of information for a transfer decision (2026-08-27, "audit against
real GW2 expert reasoning"). Real, general FPL community wisdom (checked
live via web search before writing this, not assumed): the standing advice
against an early wildcard is explicitly about INFORMATION SUFFICIENCY -
"limited information available about player performances... by GW5-6 you
should know much more about minutes, form, new signings" - not merely
"transferring costs points" (this project already prices that via
`HIT_COST`) or "raw EV might be noisy" (already priced via `robustness.py`/
`projection_confidence.py`). What was genuinely missing: a real, mechanistic
answer to "would WAITING actually teach us anything material here, or is
this decision already about as evidenced as it's going to get for a while."

Deliberately NOT a forecast of what next week's real evidence will say
(this project never fabricates football outcomes) - a real, disclosed
SENSITIVITY check: "if the exact same real Understat/minutes-evidence
pipeline that already computed this player's CURRENT
`projection_confidence` ran again after one more real match-equivalent of
data, would the resulting label actually change." Reuses
`projection_confidence.py`'s own real, disclosed match-count thresholds
directly (imported, not redefined) - the same honest bar, not a second
invented one. Never touches `expected_points()`/`expected_minutes()` and
never changes any real number the decision already used - this is a pure,
read-only, INFORMATIONAL companion to `TransferDecisionAnalysis`, not a
new gate (the user's own explicit "do not hard-code a hold" constraint -
see `decision_analysis.py`'s wiring, which surfaces this as a disclosed
field, never as an automatic REVIEW/ROLL override on top of the existing
evidence-confidence gate)."""
import sqlite3
from dataclasses import dataclass

from fpl_agent.models.projection_confidence import (
    _DATA_HIGH_MATCHES,
    _DATA_MEDIUM_MATCHES,
    _DATA_VERY_HIGH_MATCHES,
    _LEVEL_RANK,
    assess_projection_confidence,
)

# Real, disclosed assumption (stated explicitly, not hidden): "one more
# real gameweek" contributes roughly one more full match-equivalent of
# Understat evidence - the same real unit `projection_confidence.py`'s own
# thresholds are expressed in. A genuine best case (the player starts and
# plays a full match) - real absence next week (injury, rotation, a blank
# gameweek) would deliver strictly less, stated as a limitation below.
_ASSUMED_NEXT_GW_MATCH_EQUIVALENT = 1.0


def _matches_to_data_confidence(matches_played: float) -> str:
    """Pure mirror of `projection_confidence.py`'s own real
    matches-played-only threshold ladder (the top branch of
    `assess_projection_confidence`, before the prior-row/cross-league
    fallback branches, which don't apply once a real current-season sample
    already exists - both this player and the +1 projection below only
    ever hit this branch, since a real current match already exists for
    every player this function is called on)."""
    if matches_played >= _DATA_VERY_HIGH_MATCHES:
        return "VERY_HIGH"
    if matches_played >= _DATA_HIGH_MATCHES:
        return "HIGH"
    if matches_played >= _DATA_MEDIUM_MATCHES:
        return "MEDIUM"
    if matches_played > 0:
        return "LOW"
    return "VERY_LOW"


@dataclass(frozen=True)
class InformationValueAssessment:
    player_id: int
    current_data_confidence: str
    projected_data_confidence_next_gw: str
    data_confidence_would_upgrade: bool
    minutes_confidence: str
    minutes_confidence_reason: str
    minutes_would_likely_improve_by_waiting: bool
    summary: str


def assess_information_value(conn: sqlite3.Connection, player_id: int) -> InformationValueAssessment:
    pc = assess_projection_confidence(conn, player_id)
    projected_matches = pc.understat_matches_played + _ASSUMED_NEXT_GW_MATCH_EQUIVALENT
    projected = _matches_to_data_confidence(projected_matches)
    upgrades = _LEVEL_RANK[projected] > _LEVEL_RANK[pc.data_confidence]

    # Real, disclosed distinction (not the same question): minutes/role
    # confidence being capped by a real rotation-risk hedge or a genuinely
    # stale/absent basis is NOT something elapsed time alone resolves - it
    # needs a NEW real signal (team news, a confirmed lineup, a manager
    # quote), which may or may not arrive before the next deadline. Sample-
    # size-driven minutes bases (predicted_lineup_confirmed_starting,
    # blended_current_and_stale_prior) DO naturally firm up as more real
    # minutes accumulate, the same way data_confidence does.
    _TIME_RESOLVES_MINUTES_BASES = {
        "predicted_lineup_confirmed_starting", "blended_current_and_stale_prior",
        "last_season_prior_no_current_data", "current_season_only",
    }
    root_basis = pc.minutes_basis.split("+", 1)[0]
    if pc.rotation_risk:
        minutes_would_improve = False
        minutes_reason = (
            "capped by a real rotation-risk signal - resolves only with a NEW real team-news update "
            "(a confirmed lineup or manager statement), not merely by elapsed time"
        )
    elif root_basis in _TIME_RESOLVES_MINUTES_BASES and _LEVEL_RANK[pc.minutes_confidence] < _LEVEL_RANK["HIGH"]:
        minutes_would_improve = True
        minutes_reason = f"basis '{root_basis}' is sample-size-driven - a real additional match would genuinely firm this up"
    else:
        minutes_would_improve = False
        minutes_reason = f"basis '{root_basis}' at {pc.minutes_confidence} is not primarily sample-size-limited - waiting is unlikely to change it"

    if not upgrades and not minutes_would_improve:
        summary = (
            f"real waiting-value check: one more real gameweek would NOT materially improve either evidence "
            f"dimension for this player right now ({pc.data_confidence} data, {pc.minutes_confidence} minutes) - "
            f"the decision is not information-starved, deferring it buys little real evidence"
        )
    elif upgrades and not minutes_would_improve:
        summary = (
            f"real waiting-value check: data confidence would likely reach {projected} "
            f"(from {pc.data_confidence}) after one more real match, but minutes confidence would not "
            f"({minutes_reason})"
        )
    elif minutes_would_improve and not upgrades:
        summary = (
            f"real waiting-value check: minutes confidence could genuinely improve with one more real "
            f"gameweek ({minutes_reason}), though data confidence would likely stay {pc.data_confidence}"
        )
    else:
        summary = (
            f"real waiting-value check: BOTH data confidence (-> likely {projected}) and minutes confidence "
            f"({minutes_reason}) would genuinely improve with one more real gameweek - this is a real case "
            f"where waiting has meaningful expected information value"
        )

    return InformationValueAssessment(
        player_id=player_id, current_data_confidence=pc.data_confidence,
        projected_data_confidence_next_gw=projected, data_confidence_would_upgrade=upgrades,
        minutes_confidence=pc.minutes_confidence, minutes_confidence_reason=minutes_reason,
        minutes_would_likely_improve_by_waiting=minutes_would_improve, summary=summary,
    )
