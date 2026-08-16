"""
Sampled effective ownership (Pillar 1 Plan 1c). See design doc
docs/superpowers/specs/2026-08-16-decision-intelligence-plan1c-design.md.
"""
import math
import sqlite3
import time
from datetime import datetime, timezone

from fpl_agent.ingestion.fpl_api import FPLApiAdapter, SourceFetchError
from fpl_agent.ingestion.sync import update_source_health
from fpl_agent.models.effective_ownership import sample_season

OVERALL_LEAGUE_ID = 314
_ENTRIES_PER_PAGE = 50
_MAX_RANK = 10000
_DEFAULT_SAMPLE_SIZE = 750
_DEFAULT_DELAY_SECONDS = 0.15  # same politeness delay as history_sync.py
_FAILURE_TOLERANCE = 0.10  # >10% of attempted manager fetches failing = a degraded run


def select_stratified_pages(
    target_sample_size: int, entries_per_page: int = _ENTRIES_PER_PAGE, max_rank: int = _MAX_RANK
) -> list[int]:
    """Evenly-spread standings page numbers across the full rank 1..max_rank range,
    rather than clustering at the top of the list - top-of-list ranks are extreme
    overperformers, not a representative top-10k sample."""
    max_page = max_rank // entries_per_page
    n_pages = min(max(1, math.ceil(target_sample_size / entries_per_page)), max_page)
    if n_pages == 1:
        return [1]
    step = (max_page - 1) / (n_pages - 1)
    return sorted({1 + round(k * step) for k in range(n_pages)})


def _parse_entry_ids(payload) -> list[int]:
    """Guarded read of one standings page. An unexpected response shape is one skipped
    page, not an uncaught KeyError/TypeError that discards a whole in-progress run of
    hundreds of requests. Entry ids are coerced to int here too: they flow into
    source_name=f"fpl_api_entry_picks_{entry_id}_{event}", which raw_store turns into a
    filename, so an untrusted payload string must never reach it verbatim."""
    try:
        results = payload["standings"]["results"]
    except (KeyError, TypeError):
        return []
    if not isinstance(results, list):
        return []
    entry_ids = []
    for r in results:
        try:
            entry_ids.append(int(r["entry"]))
        except (KeyError, TypeError, ValueError):
            continue
    return entry_ids


def _parse_picks(payload) -> list[tuple[int, int]] | None:
    """Guarded read of one manager's picks, as (element, multiplier) pairs. None means
    a malformed payload - counted as a manager-level failure like any fetch error,
    never an uncaught exception that loses the run. A single unparseable pick fails the
    whole manager rather than contributing a partial squad, which would understate
    every other player's ownership against a denominator that counted this manager."""
    try:
        picks = payload["picks"]
    except (KeyError, TypeError):
        return None
    if not isinstance(picks, list):
        return None
    parsed = []
    for p in picks:
        try:
            parsed.append((int(p["element"]), int(p["multiplier"])))
        except (KeyError, TypeError, ValueError):
            return None
    return parsed


def sample_effective_ownership(
    conn: sqlite3.Connection,
    event: int,
    target_sample_size: int = _DEFAULT_SAMPLE_SIZE,
    force: bool = False,
    delay: float = _DEFAULT_DELAY_SECONDS,
) -> dict:
    """Bounded, rank-stratified sample of top-10k Overall league picks for one
    already-locked event. Idempotent per event unless force=True (the whole event's
    rows are one atomic batch from one coherent set of sampled managers, not
    accumulated row-by-row like sync-history's per-player skip). Scoped to the current
    season throughout - events.id is 1-38 and reused every season, so an event-only key
    would make next season's GW1 collide with this season's."""
    season = sample_season(conn)
    existing = conn.execute(
        "SELECT COUNT(*) AS n FROM player_sample_ownership_history WHERE event=? AND season=?",
        (event, season),
    ).fetchone()["n"]
    if existing and not force:
        return {
            "skipped": True, "event": event, "sample_size": 0, "players_sampled": 0,
            "managers_failed": 0, "unknown_players_dropped": 0,
        }

    event_row = conn.execute("SELECT deadline_time_epoch FROM events WHERE id=?", (event,)).fetchone()
    if event_row is None:
        raise ValueError(f"event {event} does not exist")
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    if event_row["deadline_time_epoch"] > now_epoch:
        raise ValueError(f"event {event} has not locked yet (deadline still ahead) - picks aren't available")

    adapter = FPLApiAdapter()
    pages = select_stratified_pages(target_sample_size)
    entry_ids: list[int] = []
    for page in pages:
        try:
            fetch = adapter.fetch_league_standings(OVERALL_LEAGUE_ID, page)
        except SourceFetchError:
            fetch = None
        finally:
            time.sleep(delay)
        if fetch is None:
            continue
        entry_ids.extend(_parse_entry_ids(fetch.data))
    entry_ids = entry_ids[:target_sample_size]

    agg: dict[int, dict[str, int]] = {}
    fetched = 0
    failed: list[int] = []
    for entry_id in entry_ids:
        try:
            fetch = adapter.fetch_entry_picks(entry_id, event)
        except SourceFetchError:
            failed.append(entry_id)
            fetch = None
        finally:
            time.sleep(delay)
        if fetch is None:
            continue

        picks = _parse_picks(fetch.data)
        if picks is None:
            failed.append(entry_id)
            continue

        for pid, mult in picks:
            bucket = agg.setdefault(
                pid, {"owned_count": 0, "captained_count": 0, "sum_multiplier": 0, "sum_multiplier_sq": 0}
            )
            bucket["owned_count"] += 1
            if mult >= 2:
                bucket["captained_count"] += 1
            bucket["sum_multiplier"] += mult
            bucket["sum_multiplier_sq"] += mult * mult

        fetched += 1

    # player_id has a real FK to players(id) and foreign_keys=ON is set on every
    # connection, so an element id we haven't synced locally yet (a player added
    # between the last `fpl sync` and this run) would fail the whole executemany with
    # IntegrityError and discard an entire run's worth of requests. Drop just that
    # player's rows; the aggregation for known players still commits.
    known_player_ids = {r["id"] for r in conn.execute("SELECT id FROM players")}
    unknown_player_ids = [pid for pid in agg if pid not in known_player_ids]
    for pid in unknown_player_ids:
        del agg[pid]

    sample_size = fetched
    if sample_size > 0:
        # Delete-then-insert must be one atomic unit committed together: if force's
        # DELETE landed in a prior implicit transaction and total fetch failure left
        # sample_size == 0, update_source_health's own commit() below would otherwise
        # flush the DELETE alone and silently wipe a previously-good sample.
        if force:
            conn.execute(
                "DELETE FROM player_sample_ownership_history WHERE event=? AND season=?",
                (event, season),
            )
        now = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            "INSERT INTO player_sample_ownership_history "
            "(player_id, event, season, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (pid, event, season, sample_size, b["owned_count"], b["captained_count"], b["sum_multiplier"], b["sum_multiplier_sq"], now)
                for pid, b in agg.items()
            ],
        )
        conn.commit()

    # update_source_health's success branch (shared by every source in this codebase,
    # not this plan's to change) zeroes failure_count and ignores `error` entirely - so
    # success=sample_size>0 would record a run where 700 of 750 manager fetches failed
    # as perfectly healthy. Report degradation instead, but with a tolerance rather than
    # zero-tolerance: `fpl doctor`/`readiness`/`source-status` treat any failure_count>0
    # as DEGRADED for the whole system, and one 404 out of ~750 sequential requests is
    # normal noise that self-heals on the next run - a genuinely broken or rate-limiting
    # API blows well past the threshold.
    attempted = fetched + len(failed)
    degraded = attempted > 0 and len(failed) > _FAILURE_TOLERANCE * attempted
    update_source_health(
        conn, "fpl_eo_sample",
        success=(sample_size > 0 and not degraded),
        error=f"{len(failed)} of {attempted} manager fetch(es) failed" if failed else None,
    )

    return {
        "skipped": False, "event": event, "sample_size": sample_size,
        "players_sampled": len(agg), "managers_failed": len(failed),
        "unknown_players_dropped": len(unknown_player_ids),
    }
