"""
Sampled effective ownership derivation (Pillar 1 Plan 1c). Pure functions over
player_sample_ownership_history's FACTS - no I/O beyond reading that table. See
design doc docs/superpowers/specs/2026-08-16-decision-intelligence-plan1c-design.md.
"""
import math
import sqlite3
from dataclasses import dataclass

from fpl_agent.models.rules import current_season

CONFIDENCE_Z = 1.96  # 95% CI
UNKNOWN_SEASON = "unknown"


def sample_season(conn: sqlite3.Connection) -> str:
    """The season label sampled-EO rows are written and read under. Same "YYYY-YY"
    convention as rules.season (and the same "unknown" fallback sync.py's
    _extract_season uses when the bootstrap hasn't been synced yet), so a row written
    by one sampling run is always found again by the reader that follows it."""
    return current_season(conn) or UNKNOWN_SEASON


@dataclass(frozen=True)
class SampleEOEstimate:
    player_id: int
    event: int
    sample_size: int
    eo_percent: float
    raw_owned_percent: float
    margin_of_error_pp: float


def get_all_sample_eo(conn: sqlite3.Connection, event: int | None = None) -> dict[int, SampleEOEstimate]:
    """Latest (or given) event's sampled EO for every player with >=1 owner in the
    sample. An empty dict means no sampling run has ever produced rows for that
    event - callers must fall back to raw ownership, never treat this as all-zero EO.

    Always scoped to the current season: events.id is 1-38 and reused every season, so
    an unscoped MAX(event) would happily return a previous season's GW38 sample for
    player ids FPL has since reassigned."""
    season = sample_season(conn)
    if event is None:
        row = conn.execute(
            "SELECT MAX(event) AS event FROM player_sample_ownership_history WHERE season=?",
            (season,),
        ).fetchone()
        event = row["event"] if row and row["event"] is not None else None
        if event is None:
            return {}

    rows = conn.execute(
        "SELECT player_id, sample_size, owned_count, sum_multiplier, sum_multiplier_sq "
        "FROM player_sample_ownership_history WHERE event=? AND season=?",
        (event, season),
    ).fetchall()

    result: dict[int, SampleEOEstimate] = {}
    for r in rows:
        n = r["sample_size"]
        mean = r["sum_multiplier"] / n
        variance = max(r["sum_multiplier_sq"] / n - mean * mean, 0.0)
        result[r["player_id"]] = SampleEOEstimate(
            player_id=r["player_id"], event=event, sample_size=n,
            eo_percent=mean * 100,
            raw_owned_percent=100 * r["owned_count"] / n,
            margin_of_error_pp=CONFIDENCE_Z * math.sqrt(variance / n) * 100,
        )
    return result


def get_sample_eo(conn: sqlite3.Connection, player_id: int, event: int | None = None) -> SampleEOEstimate | None:
    """Single-player lookup. None only when no sample exists for the resolved event
    at all; a real SampleEOEstimate(eo_percent=0.0, ...) when a sample exists but
    this player had zero owners in it - a genuine measured zero, not a data gap."""
    all_eo = get_all_sample_eo(conn, event)
    if not all_eo:
        return None
    if player_id in all_eo:
        return all_eo[player_id]
    any_estimate = next(iter(all_eo.values()))
    return SampleEOEstimate(
        player_id=player_id, event=any_estimate.event, sample_size=any_estimate.sample_size,
        eo_percent=0.0, raw_owned_percent=0.0, margin_of_error_pp=0.0,
    )
