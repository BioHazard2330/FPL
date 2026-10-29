"""Where the overall-rank targets sit: the total of the manager ranked 1,000th, 10,000th and 100,000th overall.

FPL's overall league (id 314) is public and paged fifty to a page, so the manager at rank r is on page ceil(r / 50). Its
`rank_sort` is the strict position (ties share a `rank`), so the row whose `rank_sort` equals the target is the boundary.
One call per target, at most every `SYNC_HOURS`; each reading is kept per gameweek so the pace of a target can be
measured once a few gameweeks of readings exist."""
import logging
import math
import sqlite3
from datetime import datetime, timedelta, timezone

from fpl_agent.ingestion.fpl_api import FPLApiAdapter, SourceFetchError

OVERALL_LEAGUE = 314
TARGETS = (1_000, 10_000, 100_000)
PAGE_SIZE = 50
SYNC_HOURS = 6
_META_KEY = "rank_threshold_synced_at"
_logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _due(conn: sqlite3.Connection, force: bool) -> bool:
    if force:
        return True
    row = conn.execute("SELECT value FROM app_meta WHERE key=?", (_META_KEY,)).fetchone()
    try:
        last = datetime.fromisoformat(row["value"]) if row and row["value"] else None
    except ValueError:
        last = None
    return last is None or datetime.now(timezone.utc) - last >= timedelta(hours=SYNC_HOURS)


def boundary_total(results: list[dict], target: int) -> int | None:
    """The total of the manager in strict position `target` on one standings page, or None if he is not on it."""
    for r in results:
        if r.get("rank_sort") == target:
            return int(r["total"])
    return None


def sync_rank_thresholds(conn: sqlite3.Connection, client: FPLApiAdapter | None = None, force: bool = False) -> dict:
    from fpl_agent.ingestion.leagues import _latest_started_event
    from fpl_agent.models.rules import current_season

    if not _due(conn, force):
        return {"status": "fresh"}
    event = _latest_started_event(conn)
    season = current_season(conn)
    if event is None or season is None:
        return {"status": "no_event"}
    client = client or FPLApiAdapter()
    at = _now()
    stored = {}
    for target in TARGETS:
        page = math.ceil(target / PAGE_SIZE)
        try:
            data = client.fetch_league_standings(OVERALL_LEAGUE, page).data
        except SourceFetchError as e:
            _logger.warning("rank threshold %s: page %s failed: %s", target, page, e)
            continue
        total = boundary_total((data.get("standings") or {}).get("results") or [], target)
        if total is None:
            continue
        conn.execute(
            "INSERT INTO rank_threshold (season, event, rank_target, total, retrieved_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(season, event, rank_target) DO UPDATE SET total=excluded.total, retrieved_at=excluded.retrieved_at",
            (season, event, target, total, at),
        )
        stored[target] = total
    if stored:
        conn.execute(
            "INSERT INTO app_meta (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (_META_KEY, at, at),
        )
    conn.commit()
    return {"status": "synced", "event": event, "totals": stored}


def latest_thresholds(conn: sqlite3.Connection) -> dict[int, dict]:
    """{target rank: {event, total, retrieved_at}} from the latest reading of each target."""
    rows = conn.execute(
        "SELECT rank_target, event, total, retrieved_at FROM rank_threshold t WHERE retrieved_at = "
        "(SELECT MAX(retrieved_at) FROM rank_threshold u WHERE u.rank_target = t.rank_target)"
    ).fetchall()
    return {r["rank_target"]: {"event": r["event"], "total": r["total"], "retrieved_at": r["retrieved_at"]} for r in rows}
