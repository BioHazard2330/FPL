"""
Template detection (section 76): the highest-owned players per position, purely
from current ownership data - no modelling involved.
"""

import sqlite3
from dataclasses import dataclass

DEFAULT_TOP_N_PER_POSITION = 3


@dataclass(frozen=True)
class TemplatePlayer:
    player_id: int
    web_name: str
    position: str
    ownership_percent: float


def get_template(conn: sqlite3.Connection, top_n_per_position: int = DEFAULT_TOP_N_PER_POSITION) -> list[TemplatePlayer]:
    rows = conn.execute(
        "SELECT p.id, p.web_name, et.singular_name_short AS position, oh.selected_by_percent "
        "FROM players p "
        "JOIN element_types et ON et.id = p.element_type "
        "JOIN player_ownership_history oh ON oh.player_id = p.id AND oh.valid_until IS NULL "
        "WHERE p.removed = 0 "
        "ORDER BY et.singular_name_short, oh.selected_by_percent DESC"
    ).fetchall()

    by_position: dict[str, list[TemplatePlayer]] = {}
    for r in rows:
        bucket = by_position.setdefault(r["position"], [])
        if len(bucket) < top_n_per_position:
            bucket.append(
                TemplatePlayer(
                    player_id=r["id"], web_name=r["web_name"], position=r["position"],
                    ownership_percent=r["selected_by_percent"],
                )
            )

    result = []
    for players in by_position.values():
        result.extend(players)
    return result
