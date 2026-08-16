"""
Template detection (section 76): the highest-owned players per position. Uses
sampled effective ownership (Plan 1c) when a sample exists for the latest event,
falling back to raw current ownership otherwise - never silently blank.
"""
import sqlite3
from dataclasses import dataclass

from fpl_agent.models.effective_ownership import get_all_sample_eo

DEFAULT_TOP_N_PER_POSITION = 3


@dataclass(frozen=True)
class TemplatePlayer:
    player_id: int
    web_name: str
    position: str
    ownership_percent: float
    effective_ownership_percent: float | None
    eo_source: str  # "sampled" or "raw"


def get_template(conn: sqlite3.Connection, top_n_per_position: int = DEFAULT_TOP_N_PER_POSITION) -> list[TemplatePlayer]:
    rows = conn.execute(
        "SELECT p.id, p.web_name, et.singular_name_short AS position, oh.selected_by_percent "
        "FROM players p "
        "JOIN element_types et ON et.id = p.element_type "
        "JOIN player_ownership_history oh ON oh.player_id = p.id AND oh.valid_until IS NULL "
        "WHERE p.removed = 0"
    ).fetchall()

    eo_by_player = get_all_sample_eo(conn)

    ranked = []
    for r in rows:
        eo = eo_by_player.get(r["id"])
        if eo is not None:
            sort_value = eo.eo_percent
            eo_percent, eo_source = sort_value, "sampled"
        else:
            # Absent from a non-empty sample means "no measurement was taken for this
            # player", not a measured zero - ~750 sampled managers can't cover every
            # player. Fall back to this row's own raw ownership, exactly as when no
            # sample exists at all, rather than claiming a fabricated sampled 0.0%.
            sort_value = r["selected_by_percent"]
            eo_percent, eo_source = None, "raw"
        ranked.append((r["position"], -sort_value, r, eo_percent, eo_source))

    ranked.sort(key=lambda t: (t[0], t[1]))

    by_position: dict[str, list[TemplatePlayer]] = {}
    result = []
    for _, _, r, eo_percent, eo_source in ranked:
        bucket = by_position.setdefault(r["position"], [])
        if len(bucket) < top_n_per_position:
            player = TemplatePlayer(
                player_id=r["id"], web_name=r["web_name"], position=r["position"],
                ownership_percent=r["selected_by_percent"],
                effective_ownership_percent=eo_percent, eo_source=eo_source,
            )
            bucket.append(player)
            result.append(player)
    return result
