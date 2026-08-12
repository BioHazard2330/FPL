"""
Differential engine (section 58). Ownership thresholds and the risk-bucket mapping
below are deliberate, documented heuristics - not calibrated against any historical
differential-success data (none exists yet this season).
"""

import sqlite3
from dataclasses import dataclass

from fpl_agent.models.expected_points import expected_points

MAX_OWNERSHIP_PERCENT = 5.0
MIN_MEDIAN_XP = 2.0


@dataclass(frozen=True)
class Differential:
    player_id: int
    web_name: str
    position: str
    ownership_percent: float
    median: float
    ceiling: float
    confidence: str
    risk: str  # low-risk / medium-risk / high-risk / extreme-punt


def _risk_bucket(ownership_percent: float, confidence: str) -> str:
    if ownership_percent < 1.0:
        return "extreme-punt"
    if confidence == "LOW":
        return "high-risk"
    if confidence == "MEDIUM":
        return "medium-risk"
    return "low-risk"


def find_differentials(
    conn: sqlite3.Connection,
    n_gw: int = 1,
    max_ownership: float = MAX_OWNERSHIP_PERCENT,
    min_median_xp: float = MIN_MEDIAN_XP,
) -> list[Differential]:
    rows = conn.execute(
        "SELECT p.id, p.web_name, et.singular_name_short AS position, oh.selected_by_percent "
        "FROM players p "
        "JOIN element_types et ON et.id = p.element_type "
        "JOIN player_ownership_history oh ON oh.player_id = p.id AND oh.valid_until IS NULL "
        "WHERE p.removed = 0 AND oh.selected_by_percent < ?",
        (max_ownership,),
    ).fetchall()

    results = []
    for r in rows:
        ep = expected_points(conn, r["id"], n_gw=n_gw)
        if ep.median < min_median_xp:
            continue
        results.append(
            Differential(
                player_id=r["id"], web_name=r["web_name"], position=r["position"],
                ownership_percent=r["selected_by_percent"],
                median=ep.median, ceiling=ep.ceiling, confidence=ep.confidence,
                risk=_risk_bucket(r["selected_by_percent"], ep.confidence),
            )
        )
    results.sort(key=lambda d: d.median, reverse=True)
    return results
