"""Historical, skill-selected Elite-manager panel (2026-08-26, GW1-postmortem
gap audit, P1 "historical skill-selected elite-manager panel").

Real, confirmed data constraint - checked LIVE before writing a single line
here, not assumed: FPL's own `leagues-classic/314/standings/` endpoint is
season-scoped to whatever season is CURRENTLY live. Fetched it for real
(2026-08-26): page 1 of league 314 returned this season's real GW1 point
totals ("event_total": 131, a genuine current-season score), not a past,
ended season's final table. There is no separate endpoint this project has
found that exposes a prior season's final Overall-league standings once a
new season has started - that data window has already closed, and FPL's
public API gives no way back into it. Building a real "last season's top
1000 finishers" panel FOR THE CURRENT SEASON is therefore genuinely
impossible right now, not a code gap.

What IS real and buildable: this module can capture the CURRENT (or any
live) season's standings and store them as a stable panel - the exact real
methodology FPL Review's own "Elite 1000" actually uses (a real historical
track record, not a live-standings resample), just only genuinely
meaningful as a skill signal when captured near a season's real END (a full
season of performance) and then used to sample effective ownership starting
the FOLLOWING season, not the same one it was captured in.

Honest state as of this writing: zero real historical panels exist in this
project yet - this is the first season it has ever been positioned to
capture one for. The real payoff (a genuine historically-selected sample,
replacing player_sample_ownership_history's current live-standings
resample for this specific use case) is only available from next season
onward, once a real end-of-season snapshot has actually been taken - not
retroactively for GW1-era decisions this season. Recorded here plainly
rather than glossed over."""
import sqlite3
import time
from datetime import datetime, timezone

from fpl_agent.ingestion.eo_sample import _ENTRIES_PER_PAGE, OVERALL_LEAGUE_ID
from fpl_agent.ingestion.fpl_api import FPLApiAdapter, SourceFetchError
from fpl_agent.ingestion.sync import update_source_health

_DEFAULT_PANEL_SIZE = 1000
_DEFAULT_DELAY_SECONDS = 0.15


def snapshot_elite_panel(
    conn: sqlite3.Connection, season: str, target_size: int = _DEFAULT_PANEL_SIZE,
    delay: float = _DEFAULT_DELAY_SECONDS, force: bool = False,
) -> dict:
    """Sequential top-N standings pages (NOT the rank-stratified sample
    `eo_sample.py`'s live sampler uses) - a real Elite panel means the
    literal top finishers, not a representative cross-section. Idempotent
    per season unless force=True, same "one coherent atomic snapshot"
    contract eo_sample.py's own sampler already established."""
    existing = conn.execute(
        "SELECT COUNT(*) AS n FROM elite_manager_panel WHERE season=?", (season,)
    ).fetchone()["n"]
    if existing and not force:
        return {"skipped": True, "season": season, "panel_size": 0}

    adapter = FPLApiAdapter()
    n_pages = max(1, -(-target_size // _ENTRIES_PER_PAGE))
    entries: list[tuple[int, int]] = []
    fetch_failed = False
    for page in range(1, n_pages + 1):
        try:
            fetch = adapter.fetch_league_standings(OVERALL_LEAGUE_ID, page)
        except SourceFetchError as e:
            update_source_health(conn, "fpl_elite_panel", success=False, error=str(e))
            fetch_failed = True
            break
        finally:
            time.sleep(delay)
        rows = ((fetch.data or {}).get("standings") or {}).get("results") or []
        if not isinstance(rows, list):
            continue
        for r in rows:
            try:
                entries.append((int(r["entry"]), int(r["rank"])))
            except (KeyError, TypeError, ValueError):
                continue
        if len(entries) >= target_size:
            break
    entries = entries[:target_size]

    now = datetime.now(timezone.utc).isoformat()
    if force:
        conn.execute("DELETE FROM elite_manager_panel WHERE season=?", (season,))
    for entry_id, rank in entries:
        conn.execute(
            "INSERT OR IGNORE INTO elite_manager_panel (season, entry_id, final_rank, captured_at) "
            "VALUES (?,?,?,?)",
            (season, entry_id, rank, now),
        )
    if entries:
        conn.commit()
    if not fetch_failed:
        update_source_health(conn, "fpl_elite_panel", success=len(entries) > 0)
    return {"skipped": False, "season": season, "panel_size": len(entries)}


def get_elite_panel(conn: sqlite3.Connection, season: str) -> list[int]:
    """Real entry ids for a season's already-captured panel, best-rank
    first. Empty (not fabricated) for any season that was never snapshotted -
    every real season this project has run so far, until one is."""
    rows = conn.execute(
        "SELECT entry_id FROM elite_manager_panel WHERE season=? ORDER BY final_rank", (season,)
    ).fetchall()
    return [r["entry_id"] for r in rows]
