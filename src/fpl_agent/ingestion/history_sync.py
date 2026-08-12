import time
from datetime import datetime, timezone

from fpl_agent.database.connection import get_connection
from fpl_agent.ingestion.fpl_api import FPLApiAdapter, SourceFetchError
from fpl_agent.ingestion.sync import update_source_health
from fpl_agent.normalization.fpl_core import normalize_season_history

_DEFAULT_DELAY_SECONDS = 0.15  # politeness delay between per-player requests, section 23


def _upsert_season_history(conn, rows: list[dict]) -> None:
    if not rows:
        return
    now = datetime.now(timezone.utc).isoformat()
    cols = list(rows[0].keys())
    all_cols = cols + ["retrieved_at"]
    placeholders = ",".join(["?"] * len(all_cols))
    updates = ",".join(f"{c}=excluded.{c}" for c in all_cols if c not in ("player_id", "season_name"))
    sql = (
        f"INSERT INTO player_season_history ({','.join(all_cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(player_id, season_name) DO UPDATE SET {updates}"
    )
    conn.executemany(sql, [tuple(r[c] for c in cols) + (now,) for r in rows])


def sync_player_season_history(
    limit: int | None = None, force: bool = False, delay: float = _DEFAULT_DELAY_SECONDS
) -> dict:
    """Throttled, per-player fetch of career history (element-summary). Too slow/heavy
    to run on every `fpl sync` — skips players who already have history unless forced."""
    conn = get_connection()
    try:
        all_ids = [r["id"] for r in conn.execute("SELECT id FROM players WHERE removed=0 ORDER BY id").fetchall()]

        if force:
            remaining_ids = all_ids
        else:
            already = {
                r["player_id"] for r in conn.execute("SELECT DISTINCT player_id FROM player_season_history").fetchall()
            }
            remaining_ids = [pid for pid in all_ids if pid not in already]
        already_had_history = len(all_ids) - len(remaining_ids)

        if limit is not None:
            player_ids = remaining_ids[:limit]
            limit_skipped = len(remaining_ids) - len(player_ids)
        else:
            player_ids = remaining_ids
            limit_skipped = 0

        adapter = FPLApiAdapter()
        fetched = 0
        failed: list[int] = []

        for pid in player_ids:
            try:
                fetch = adapter.fetch_element_summary(pid)
            except SourceFetchError:
                failed.append(pid)
                continue

            rows = normalize_season_history(pid, fetch.data)
            _upsert_season_history(conn, rows)
            conn.commit()
            fetched += 1
            time.sleep(delay)

        update_source_health(
            conn, "fpl_api_element_summary",
            success=not failed,
            error=f"{len(failed)} player(s) failed: {failed[:10]}" if failed else None,
        )

        return {
            "fetched": fetched,
            "already_had_history": already_had_history,
            "limit_skipped": limit_skipped,
            "failed": failed,
        }
    finally:
        conn.close()
