"""
Differential engine (section 58). Ownership thresholds and the risk-bucket mapping
below are deliberate, documented heuristics - not calibrated against any historical
differential-success data (none exists yet this season). Uses sampled effective
ownership (Plan 1c) for the live (as_of_date=None) path when a sample exists; the
as_of_date historical/backtest path stays on raw ownership (EO backfill only covers
the current season's already-elapsed events, not general backtest integration).
"""
import sqlite3
from dataclasses import dataclass
from types import SimpleNamespace

from fpl_agent.models.effective_ownership import get_all_sample_eo
from fpl_agent.models.expected_points import core_expected_points, expected_points

MAX_OWNERSHIP_PERCENT = 5.0
MIN_MEDIAN_XP = 2.0


@dataclass(frozen=True)
class Differential:
    player_id: int
    web_name: str
    position: str
    ownership_percent: float
    effective_ownership_percent: float | None
    eo_source: str  # "sampled" or "raw"
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
    as_of_date: str | None = None,
) -> list[Differential]:
    if as_of_date is None:
        ownership_clause, ownership_params = "oh.valid_until IS NULL", ()
    else:
        ownership_clause = "oh.valid_from <= ? AND (oh.valid_until IS NULL OR oh.valid_until > ?)"
        ownership_params = (as_of_date, as_of_date)

    rows = conn.execute(
        f"SELECT p.id, p.web_name, et.singular_name_short AS position, oh.selected_by_percent "
        f"FROM players p "
        f"JOIN element_types et ON et.id = p.element_type "
        f"JOIN player_ownership_history oh ON oh.player_id = p.id AND {ownership_clause} "
        f"WHERE p.removed = 0",
        ownership_params,
    ).fetchall()

    eo_by_player = get_all_sample_eo(conn) if as_of_date is None else {}

    results = []
    for r in rows:
        eo = eo_by_player.get(r["id"])
        if eo is not None:
            filter_ownership = eo.eo_percent
            eo_percent, eo_source = filter_ownership, "sampled"
        else:
            # Absent from a non-empty sample means "no measurement was taken for this
            # player", not a measured zero - ~750 sampled managers can't cover every
            # player. Treating it as 0.0 handed _risk_bucket an "extreme-punt" label for
            # players who may in fact be widely owned, so fall back to this row's own
            # raw ownership, exactly as when no sample exists at all.
            filter_ownership = r["selected_by_percent"]
            eo_percent, eo_source = None, "raw"

        if filter_ownership >= max_ownership:
            continue

        if as_of_date is None:
            ep = expected_points(conn, r["id"], n_gw=n_gw)
        else:
            core = core_expected_points(conn, r["id"], as_of_date=as_of_date)
            ep = SimpleNamespace(median=core.total, ceiling=core.total, confidence="historical")
        if ep.median < min_median_xp:
            continue
        results.append(
            Differential(
                player_id=r["id"], web_name=r["web_name"], position=r["position"],
                ownership_percent=r["selected_by_percent"],
                effective_ownership_percent=eo_percent, eo_source=eo_source,
                median=ep.median, ceiling=ep.ceiling, confidence=ep.confidence,
                risk=_risk_bucket(filter_ownership, ep.confidence),
            )
        )
    results.sort(key=lambda d: d.median, reverse=True)
    return results
