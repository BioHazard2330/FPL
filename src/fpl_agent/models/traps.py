"""
Trap engine (section 60): popular players (high ownership) whose underlying FPL
case is deteriorating. min_ownership is a documented heuristic threshold. Uses
sampled effective ownership (Plan 1c) for the ownership filter/sort when a sample
exists, raw ownership otherwise.
"""
import sqlite3
from dataclasses import dataclass

from fpl_agent.models.availability import classify
from fpl_agent.models.effective_ownership import get_all_sample_eo
from fpl_agent.models.expected_minutes import expected_minutes

MIN_OWNERSHIP_PERCENT = 10.0
LOW_MINUTES_THRESHOLD = 60.0


@dataclass(frozen=True)
class Trap:
    player_id: int
    web_name: str
    position: str
    ownership_percent: float
    effective_ownership_percent: float | None
    eo_source: str  # "sampled" or "raw"
    reasons: list[str]


def _price_falling(conn: sqlite3.Connection, player_id: int) -> bool:
    rows = conn.execute(
        "SELECT value_tenths FROM player_price_history WHERE player_id=? ORDER BY valid_from DESC LIMIT 2",
        (player_id,),
    ).fetchall()
    if len(rows) < 2:
        return False
    return rows[0]["value_tenths"] < rows[1]["value_tenths"]


def find_traps(conn: sqlite3.Connection, min_ownership: float = MIN_OWNERSHIP_PERCENT) -> list[Trap]:
    rows = conn.execute(
        "SELECT p.id, p.web_name, et.singular_name_short AS position, p.status, oh.selected_by_percent, "
        "s.chance_of_playing_this_round, s.chance_of_playing_next_round "
        "FROM players p "
        "JOIN element_types et ON et.id = p.element_type "
        "JOIN player_ownership_history oh ON oh.player_id = p.id AND oh.valid_until IS NULL "
        "LEFT JOIN player_stats_snapshot s ON s.id = ("
        "    SELECT id FROM player_stats_snapshot WHERE player_id = p.id ORDER BY retrieved_at DESC LIMIT 1"
        ") "
        "WHERE p.removed = 0"
    ).fetchall()

    eo_by_player = get_all_sample_eo(conn)

    results = []
    for r in rows:
        eo = eo_by_player.get(r["id"])
        if eo is not None:
            filter_ownership = eo.eo_percent
            eo_percent, eo_source = filter_ownership, "sampled"
        else:
            # Absent from a non-empty sample means "no measurement was taken for this
            # player", not a measured zero - ~750 sampled managers can't cover every
            # player. Fall back to this row's own raw ownership, exactly as when no
            # sample exists at all, rather than claiming a fabricated sampled 0.0%.
            filter_ownership = r["selected_by_percent"]
            eo_percent, eo_source = None, "raw"

        if filter_ownership < min_ownership:
            continue

        reasons = []
        classification = classify(r["status"], r["chance_of_playing_this_round"], r["chance_of_playing_next_round"])
        if classification != "FIT":
            reasons.append(f"availability: {classification}")

        em = expected_minutes(conn, r["id"])
        if em.expected_minutes < LOW_MINUTES_THRESHOLD:
            reasons.append(f"minutes risk: {em.expected_minutes:.0f} expected")

        if _price_falling(conn, r["id"]):
            reasons.append("price falling")

        if reasons:
            results.append(
                Trap(
                    player_id=r["id"], web_name=r["web_name"], position=r["position"],
                    ownership_percent=r["selected_by_percent"],
                    effective_ownership_percent=eo_percent, eo_source=eo_source,
                    reasons=reasons,
                )
            )

    results.sort(key=lambda t: t.effective_ownership_percent if t.effective_ownership_percent is not None else t.ownership_percent, reverse=True)
    return results
