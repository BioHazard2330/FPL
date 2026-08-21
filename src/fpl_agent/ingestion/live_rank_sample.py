"""Live overall-rank reference sampling (2026-08-21, live-gameweek layer
item 3). Reuses `ingestion/eo_sample.py`'s already-shipped, tested
stratified-sampling primitives (`select_stratified_pages`, the standings-
page/entry-picks fetch pattern, the circuit-breaker/degraded-health
reporting posture) for a different purpose than effective ownership - see
`models/live_rank.py`'s own module docstring for the real research this is
based on and the honest limitations of the resulting estimate.

The one deliberate difference from `sample_effective_ownership`: this
samples across the FULL rank range (1..total_players, not capped at
10,000) - a real, considered choice, not an oversight. EO sampling caps at
10k because it's answering "how does the competitive top tier own this
player"; this module is answering "where does MY live points total sit
among ALL ~11 million managers", and a real manager (this project's own
user included - their real 2025/26 rank was ~1,000,697, see CLAUDE.md's
my-team section) can sit anywhere in that range, not just the top 10k.

`select_weighted_stratified_pages` (2026-08-21, direct user request) -
weights the sample toward the top of the distribution instead of
`eo_sample.py::select_stratified_pages`'s flat even spread: the top 10% of
managers is where rank differences are most competitively meaningful and
where PCHIP's interpolation quality benefits most from dense anchor
coverage (`models/live_rank.py`), while the bottom 30% needs far fewer
points to establish "this score is deep in the tail" - a real, deliberate
allocation choice (50% of the sample budget in the top 10% of the rank
range, 35% in the middle 60%, 15% in the bottom 30%), not a uniform
default."""
import math
import sqlite3
import time
from datetime import datetime, timezone

from fpl_agent.ingestion.eo_sample import OVERALL_LEAGUE_ID
from fpl_agent.ingestion.fpl_api import FPLApiAdapter, SourceFetchError
from fpl_agent.ingestion.sync import update_source_health
from fpl_agent.models.effective_ownership import sample_season
from fpl_agent.models.live_rank import estimate_squad_live_points

_ENTRIES_PER_PAGE = 50
_DEFAULT_SAMPLE_SIZE = 300  # fewer than EO sampling's 750 - this needs enough
# STRATIFIED points to interpolate a curve, not per-player variance reduction.
_DEFAULT_DELAY_SECONDS = 0.15

# (upper rank fraction of total_players, sample-budget fraction) - top-heavy
# by design, see this module's own docstring.
_STRATIFICATION_TIERS = (
    (0.10, 0.50),  # top 10% of managers get 50% of the sample budget
    (0.70, 0.35),  # next 60% (10%-70%) get 35%
    (1.00, 0.15),  # bottom 30% (70%-100%) get 15%
)


def _evenly_spread_pages(n_pages_wanted: int, min_page: int, max_page: int) -> list[int]:
    """Evenly-spread page numbers within [min_page, max_page] - the same
    even-spread math `eo_sample.py::select_stratified_pages` uses, scoped
    to one tier's own sub-range instead of the whole rank space."""
    min_page, max_page = max(1, min_page), max(min_page, max_page)
    n_pages_wanted = min(max(1, n_pages_wanted), max_page - min_page + 1)
    if n_pages_wanted == 1:
        return [min_page]
    step = (max_page - min_page) / (n_pages_wanted - 1)
    return sorted({min_page + round(k * step) for k in range(n_pages_wanted)})


def select_weighted_stratified_pages(
    target_sample_size: int, total_players: int, entries_per_page: int = _ENTRIES_PER_PAGE,
) -> list[int]:
    """Top-heavy stratified page selection across 1..total_players - see
    this module's own docstring for the real tier allocation and why."""
    max_page = max(1, total_players // entries_per_page)
    pages: set[int] = set()
    tier_start_page = 1
    for upper_fraction, budget_fraction in _STRATIFICATION_TIERS:
        tier_end_page = max(tier_start_page, min(max_page, round(upper_fraction * max_page)))
        n_pages = max(1, math.ceil((target_sample_size * budget_fraction) / entries_per_page))
        pages.update(_evenly_spread_pages(n_pages, tier_start_page, tier_end_page))
        tier_start_page = tier_end_page + 1
        if tier_start_page > max_page:
            break
    return sorted(pages)
_FAILURE_TOLERANCE = 0.10
_MAX_CONSECUTIVE_FAILURES = 25


def _parse_picks_and_history(payload) -> tuple[list[tuple[int, int]], dict | None] | None:
    """Guarded read of one manager's picks + entry_history from the same
    `/entry/{id}/event/{gw}/picks/` payload eo_sample.py's `_parse_picks`
    already reads picks from - this also needs `entry_history.total_points`/
    `.points` (real cumulative-total-before-this-event derivation, see
    module docstring) from the SAME response, so it's parsed together
    rather than issuing a second request. Returns None on any malformed
    shape - a manager-level failure, same discipline `_parse_picks` uses."""
    try:
        picks_raw = payload["picks"]
    except (KeyError, TypeError):
        return None
    if not isinstance(picks_raw, list):
        return None
    picks: list[tuple[int, int]] = []
    for p in picks_raw:
        try:
            picks.append((int(p["element"]), int(p["multiplier"])))
        except (KeyError, TypeError, ValueError):
            return None
    entry_history = payload.get("entry_history")
    if not isinstance(entry_history, dict):
        entry_history = None
    return picks, entry_history


def sample_live_rank_reference(
    conn: sqlite3.Connection,
    event: int,
    live_payload: dict,
    target_sample_size: int = _DEFAULT_SAMPLE_SIZE,
    force: bool = False,
    delay: float = _DEFAULT_DELAY_SECONDS,
    max_consecutive_failures: int = _MAX_CONSECUTIVE_FAILURES,
) -> dict:
    """Bounded, full-range rank-stratified sample of real managers' live
    points for one already-locked, in-progress event. `live_payload` is the
    caller's own already-fetched `fetch_event_live(event).data` (same
    pattern `cli/main.py::_maybe_fetch_live_payload` already establishes -
    this function doesn't fetch it itself, so a caller already holding a
    fresh payload for the dashboard/live-watch loop never fetches it
    twice). Idempotent per event unless force=True, same reasoning
    sample_effective_ownership already established: the whole event's rows
    are one atomic batch from one coherent sample, not accumulated
    row-by-row."""
    season = sample_season(conn)
    existing = conn.execute(
        "SELECT COUNT(*) AS n FROM live_rank_sample WHERE event=? AND season=?",
        (event, season),
    ).fetchone()["n"]
    if existing and not force:
        return {"skipped": True, "event": event, "sample_size": 0, "managers_failed": 0, "aborted_early": False}

    event_row = conn.execute("SELECT deadline_time_epoch FROM events WHERE id=?", (event,)).fetchone()
    if event_row is None:
        raise ValueError(f"event {event} does not exist")
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    if event_row["deadline_time_epoch"] > now_epoch:
        raise ValueError(f"event {event} has not locked yet (deadline still ahead) - picks aren't available")

    total_players_row = conn.execute("SELECT value FROM app_meta WHERE key='total_players'").fetchone()
    total_players = int(total_players_row["value"]) if total_players_row else _ENTRIES_PER_PAGE * 200

    adapter = FPLApiAdapter()
    pages = select_weighted_stratified_pages(target_sample_size, total_players)
    ranked_entry_ids: list[tuple[int, int]] = []  # (entry_id, real rank on that page)
    for page in pages:
        try:
            fetch = adapter.fetch_league_standings(OVERALL_LEAGUE_ID, page)
        except SourceFetchError:
            fetch = None
        finally:
            time.sleep(delay)
        if fetch is None:
            continue
        try:
            results = fetch.data["standings"]["results"]
        except (KeyError, TypeError):
            continue
        if not isinstance(results, list):
            continue
        for r in results:
            try:
                ranked_entry_ids.append((int(r["entry"]), int(r["rank"])))
            except (KeyError, TypeError, ValueError):
                continue

    # Real, possible edge case, not just defensive paranoia: standings can
    # genuinely shift between two sequential page fetches in this same
    # loop (a manager's rank crossing a page boundary mid-run during a
    # live gameweek), which could return the same entry_id on two
    # different pages - live_rank_sample has a real UNIQUE(event, season,
    # entry_id) constraint, so an unguarded duplicate would abort the
    # whole sample with IntegrityError. First occurrence wins.
    seen_entry_ids: set[int] = set()
    deduped: list[tuple[int, int]] = []
    for entry_id, rank in ranked_entry_ids:
        if entry_id in seen_entry_ids:
            continue
        seen_entry_ids.add(entry_id)
        deduped.append((entry_id, rank))
    ranked_entry_ids = deduped[:target_sample_size]

    rows: list[tuple[int, int, int, float, float]] = []  # (entry_id, rank, pre_gw_total, live_points, current_total)
    failed: list[int] = []
    consecutive_failures = 0
    aborted_early = False
    for entry_id, rank in ranked_entry_ids:
        if consecutive_failures >= max_consecutive_failures:
            aborted_early = True
            break

        parsed = None
        try:
            fetch = adapter.fetch_entry_picks(entry_id, event)
        except SourceFetchError:
            fetch = None
        finally:
            time.sleep(delay)
        if fetch is not None:
            parsed = _parse_picks_and_history(fetch.data)

        if parsed is None or parsed[1] is None:
            failed.append(entry_id)
            consecutive_failures += 1
            continue
        consecutive_failures = 0

        picks, entry_history = parsed
        total_points = entry_history.get("total_points")
        this_event_points = entry_history.get("points")
        if total_points is None or this_event_points is None:
            failed.append(entry_id)
            continue
        pre_gw_total = total_points - this_event_points
        live_points = estimate_squad_live_points(picks, live_payload)
        current_total = pre_gw_total + live_points
        rows.append((entry_id, rank, pre_gw_total, live_points, current_total))

    sample_size = len(rows)
    if sample_size > 0:
        if force:
            conn.execute("DELETE FROM live_rank_sample WHERE event=? AND season=?", (event, season))
        now = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            "INSERT INTO live_rank_sample "
            "(event, season, entry_id, pre_gw_rank, pre_gw_total, live_points, current_total, sampled_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [(event, season, entry_id, rank, pre_gw_total, live_points, current_total, now)
             for entry_id, rank, pre_gw_total, live_points, current_total in rows],
        )
        conn.commit()

    attempted = sample_size + len(failed)
    degraded = aborted_early or (attempted > 0 and len(failed) > _FAILURE_TOLERANCE * attempted)
    error = f"{len(failed)} of {attempted} manager fetch(es) failed" if failed else None
    if aborted_early:
        error = f"{error} - aborted after {max_consecutive_failures} consecutive failures"
    update_source_health(conn, "fpl_live_rank_sample", success=(sample_size > 0 and not degraded), error=error)

    return {
        "skipped": False, "event": event, "sample_size": sample_size,
        "managers_failed": len(failed), "aborted_early": aborted_early,
    }


def get_live_rank_reference(conn: sqlite3.Connection, event: int) -> list[tuple[int, float]]:
    """Real [(pre_gw_rank, current_total)] pairs from the latest sample for
    this event - `[]` if none has ever been taken, callers must treat that
    as "no sample yet", never a fabricated empty-but-valid reference."""
    season = sample_season(conn)
    rows = conn.execute(
        "SELECT pre_gw_rank, current_total FROM live_rank_sample WHERE event=? AND season=?",
        (event, season),
    ).fetchall()
    return [(r["pre_gw_rank"], r["current_total"]) for r in rows]
