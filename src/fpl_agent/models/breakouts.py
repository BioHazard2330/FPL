"""
Breakout engine (section 59): low-ownership players with rising signal - value
ratio and value-ratio threshold are documented heuristics, not calibrated.
"""

import sqlite3
from dataclasses import dataclass

from fpl_agent.models.effective_ownership import get_all_sample_eo
from fpl_agent.models.expected_points import expected_points

MAX_OWNERSHIP_PERCENT = 10.0
MIN_VALUE_RATIO = 0.5  # median xP per £m of price


@dataclass(frozen=True)
class Breakout:
    player_id: int
    web_name: str
    position: str
    ownership_percent: float
    effective_ownership_percent: float | None
    eo_source: str  # "sampled" or "raw"
    median: float
    value_ratio: float
    reasons: list[str]


def _price_rising(conn: sqlite3.Connection, player_id: int) -> bool:
    rows = conn.execute(
        "SELECT value_tenths FROM player_price_history WHERE player_id=? ORDER BY valid_from DESC LIMIT 2",
        (player_id,),
    ).fetchall()
    if len(rows) < 2:
        return False
    return rows[0]["value_tenths"] > rows[1]["value_tenths"]


def _recent_setpiece_gain(conn: sqlite3.Connection, player_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM change_events WHERE event_type='setpiece_change' AND entity='player' AND entity_id=? "
        "ORDER BY detected_at DESC LIMIT 1",
        (player_id,),
    ).fetchone()
    return row is not None


def find_breakouts(
    conn: sqlite3.Connection,
    n_gw: int = 1,
    max_ownership: float = MAX_OWNERSHIP_PERCENT,
    min_value_ratio: float = MIN_VALUE_RATIO,
) -> list[Breakout]:
    rows = conn.execute(
        "SELECT p.id, p.web_name, et.singular_name_short AS position, p.status, oh.selected_by_percent, "
        "ph.value_tenths "
        "FROM players p "
        "JOIN element_types et ON et.id = p.element_type "
        "JOIN player_ownership_history oh ON oh.player_id = p.id AND oh.valid_until IS NULL "
        "JOIN player_price_history ph ON ph.player_id = p.id AND ph.valid_until IS NULL "
        "WHERE p.removed = 0 AND p.status = 'a' AND oh.selected_by_percent < ?",
        (max_ownership,),
    ).fetchall()

    eo_by_player = get_all_sample_eo(conn)

    results = []
    for r in rows:
        if r["value_tenths"] <= 0:
            continue
        ep = expected_points(conn, r["id"], n_gw=n_gw)
        value_ratio = ep.median / (r["value_tenths"] / 10)

        reasons = []
        if value_ratio >= min_value_ratio:
            reasons.append(f"value ratio {value_ratio:.2f} xP/£m")
        if _recent_setpiece_gain(conn, r["id"]):
            reasons.append("recently gained a set-piece role")
        if _price_rising(conn, r["id"]):
            reasons.append("price rising")

        if reasons:
            eo = eo_by_player.get(r["id"]) if eo_by_player else None
            eo_percent = eo.eo_percent if eo is not None else (0.0 if eo_by_player else None)
            eo_source = "sampled" if eo_by_player else "raw"

            results.append(
                Breakout(
                    player_id=r["id"], web_name=r["web_name"], position=r["position"],
                    ownership_percent=r["selected_by_percent"],
                    effective_ownership_percent=eo_percent, eo_source=eo_source,
                    median=ep.median,
                    value_ratio=round(value_ratio, 2), reasons=reasons,
                )
            )

    results.sort(key=lambda b: b.value_ratio, reverse=True)
    return results
