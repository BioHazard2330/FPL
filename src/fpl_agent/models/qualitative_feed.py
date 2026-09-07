"""Structured qualitative evidence -> bounded, component-targeted xP
adjustment (2026-08-26, GW1-postmortem gap audit, P0 item 3).

Hard constraints, taken directly from the audit's own explicit rules:
- Never a global weight ("do not simply assign 10% weight to AI analysis").
- Never silently mixed into the pure quant `median` every existing
  optimizer/squad-build caller already trusts - this project's own FACTS/
  DERIVED/REASONING layering rule (see decision_fusion.py's identical
  precedent: a captain/transfer verdict never gets silently overridden,
  only annotated). The adjustment is a separate, clearly-labeled field;
  `ExpectedPoints.median` is completely unaffected by this module.
- Only earns an adjustment when a real PERSISTENT_TREND exists
  (qualitative_trends.py) - the exact same 2+-real-match bar this project
  already applies to captain/transfer fusion. A single-match NEW_SIGNAL
  never adjusts a number, only a note (handled elsewhere, unaffected here).
- The adjustment size is a bounded PROPORTION of the model's own
  already-computed value for the SPECIFIC component the signal is about -
  never an invented absolute number untethered from the model's own
  baseline.

Only a few `fpl_signal` categories map cleanly onto one existing xP
component each, which is a deliberate scope decision, not an oversight:
GOAL_THREAT -> goals, CREATION -> assists, SET_PIECES -> goals.
TEAM_ATTACK/FIXTURES/TACTICAL_CHANGE have no single honest per-player
component to target (they're genuinely about the team or the fixture, not a
component of this one player's own score) and are left unmapped rather than
forced into the wrong bucket. ROLE/MINUTES signals are handled separately,
inside `expected_minutes()` itself, which already has an established
in-place-override convention (predicted-lineup/market-conviction/
rotation-risk) this mirrors rather than duplicating a second pattern for.

ROLE_CHANGE/SET_PIECE_CHANGE (2026-09-02, Phase 3 finalization deterministic
detectors, `models/role_signal_detectors.py`) are real, player-level,
single-component-mappable signals by the same honesty test above - a
detected advanced-role shift or a promoted penalty/corner/free-kick order is
genuinely about this player's own goal threat, same as GOAL_THREAT/
SET_PIECES already are - so they reuse this SAME map/interface rather than
a second adjustment pathway."""
import sqlite3
from dataclasses import dataclass

_COMPONENT_SIGNAL_MAP = {
    "GOAL_THREAT": "goals",
    "CREATION": "assists",
    "SET_PIECES": "goals",
    "ROLE_CHANGE": "goals",
    "SET_PIECE_CHANGE": "goals",
}

# Real, disclosed, uncalibrated bound - same honesty posture as every other
# threshold constant in this project (market_conviction's 10% ownership bar,
# the thin-debut 2-gameweek window, etc). Not fit to real outcome data yet -
# there is only one real analyzed gameweek in production as of this writing,
# nowhere near enough to calibrate a real magnitude against honestly.
MAX_ADJUSTMENT_FRACTION = 0.15


@dataclass(frozen=True)
class QualitativeAdjustment:
    component: str  # which ComponentBreakdown field this targets
    delta: float  # signed, already bounded - add directly to that component
    direction: str  # POSITIVE | NEGATIVE
    reason: str
    signal: str


def compute_qualitative_adjustment(conn: sqlite3.Connection, player_id: int, components) -> QualitativeAdjustment | None:
    """`components` is the real `ComponentBreakdown` `expected_points()` just
    computed for this player - the adjustment is sized off ITS values, never
    an independently-invented number. Returns None (not a fabricated
    zero-adjustment object) whenever there's no real, persistent, component-
    mappable signal - the honest, common case for almost every player right
    now, this season."""
    row = conn.execute(
        f"SELECT signal, direction, reason FROM player_fpl_implications "
        f"WHERE player_id=? AND phase='FULL_TIME' AND signal IN "
        f"({','.join('?' * len(_COMPONENT_SIGNAL_MAP))}) "
        f"ORDER BY created_at DESC LIMIT 1",
        [player_id, *_COMPONENT_SIGNAL_MAP],
    ).fetchone()
    if row is None or row["direction"] not in ("POSITIVE", "NEGATIVE"):
        return None

    from fpl_agent.models.player_intelligence import player_intelligence

    pi = player_intelligence(conn, player_id)
    is_persistent = any(
        t.signal == row["signal"] and t.label == "PERSISTENT_TREND" and t.current_direction == row["direction"]
        for t in pi.trends
    )
    if not is_persistent:
        return None

    component_name = _COMPONENT_SIGNAL_MAP[row["signal"]]
    base_value = getattr(components, component_name)
    sign = 1.0 if row["direction"] == "POSITIVE" else -1.0
    delta = round(sign * abs(base_value) * MAX_ADJUSTMENT_FRACTION, 4)

    from fpl_agent.models.text_cleanup import clean_display_text

    return QualitativeAdjustment(
        component=component_name, delta=delta, direction=row["direction"],
        reason=clean_display_text(row["reason"]), signal=row["signal"],
    )
