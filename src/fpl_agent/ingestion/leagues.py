"""The manager's classic mini-leagues, from FPL's public endpoints (no login).

`/entry/{id}/` lists every classic league the entry is in. Leagues anyone can join by the thousand (FPL's system leagues,
a YouTuber's league of 60,000) say nothing about the people a manager is actually playing against, so standings and
rivals' picks are kept only for private leagues up to `TRACK_MAX_ENTRIES` managers. In those, every rival is followed
when the league has at most `FULL_LEAGUE_MAX` entries; in larger ones the top `TOP_RIVALS` and the `NEIGHBOURS` either
side of the manager.

A rival's picks are public only for gameweeks whose deadline has passed, so a rival's team is always the one he locked
for the latest started gameweek. Synced at most every `SYNC_HOURS` hours (one entry call, one standings page per tracked
league, one picks call per rival not yet stored for that gameweek)."""
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from fpl_agent.ingestion.fpl_api import FPLApiAdapter, SourceFetchError

_logger = logging.getLogger("fpl_agent.leagues")

TRACK_MAX_ENTRIES = 300
FULL_LEAGUE_MAX = 60
TOP_RIVALS = 3
NEIGHBOURS = 3
SYNC_HOURS = 3.0
PAGE_SIZE = 50
_META_KEY = "leagues_last_synced_at"
_PAUSE_SECONDS = 0.25


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _due(conn: sqlite3.Connection, force: bool) -> bool:
    if force:
        return True
    row = conn.execute("SELECT value FROM app_meta WHERE key=?", (_META_KEY,)).fetchone()
    if row is None or not row["value"]:
        return True
    try:
        last = datetime.fromisoformat(row["value"])
    except ValueError:
        return True
    return datetime.now(timezone.utc) - last >= timedelta(hours=SYNC_HOURS)


def _latest_started_event(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT MAX(id) AS id FROM events WHERE deadline_time <= ?", (_now(),),
    ).fetchone()
    return row["id"] if row and row["id"] is not None else None


def _store_standings(conn: sqlite3.Connection, league_id: int, results: list[dict], at: str) -> None:
    conn.executemany(
        "INSERT INTO fpl_league_standing (league_id, entry_id, entry_name, player_name, rank, last_rank, total, event_total, retrieved_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(league_id, entry_id) DO UPDATE SET entry_name=excluded.entry_name, "
        "player_name=excluded.player_name, rank=excluded.rank, last_rank=excluded.last_rank, total=excluded.total, "
        "event_total=excluded.event_total, retrieved_at=excluded.retrieved_at",
        [
            (league_id, r["entry"], r.get("entry_name"), r.get("player_name"), r.get("rank"), r.get("last_rank"),
             r.get("total"), r.get("event_total"), at)
            for r in results
        ],
    )


def rivals_to_follow(rows: list[dict], my_entry: int, rank_count: int) -> list[int]:
    """Entry ids worth fetching picks for in one league's stored standings."""
    others = [r for r in rows if r["entry_id"] != my_entry]
    if rank_count <= FULL_LEAGUE_MAX:
        return [r["entry_id"] for r in others]
    mine = next((r for r in rows if r["entry_id"] == my_entry), None)
    chosen = [r["entry_id"] for r in sorted(others, key=lambda r: r["rank"] or 10**9)[:TOP_RIVALS]]
    if mine is not None and mine["rank"]:
        near = sorted(others, key=lambda r: abs((r["rank"] or 10**9) - mine["rank"]))[: 2 * NEIGHBOURS]
        chosen += [r["entry_id"] for r in near if r["entry_id"] not in chosen]
    return chosen


def _store_picks(conn: sqlite3.Connection, entry_id: int, event: int, data: dict, at: str) -> None:
    history = data.get("entry_history") or {}
    conn.execute("DELETE FROM rival_pick WHERE entry_id=? AND event=?", (entry_id, event))
    conn.executemany(
        "INSERT INTO rival_pick (entry_id, event, player_id, position, multiplier, is_captain, is_vice_captain) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (entry_id, event, p["element"], p["position"], p.get("multiplier", 1), int(bool(p.get("is_captain"))),
             int(bool(p.get("is_vice_captain"))))
            for p in data.get("picks", [])
        ],
    )
    conn.execute(
        "INSERT INTO rival_event (entry_id, event, active_chip, points, total_points, bank, value, event_transfers, "
        "event_transfers_cost, retrieved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(entry_id, event) DO UPDATE SET "
        "active_chip=excluded.active_chip, points=excluded.points, total_points=excluded.total_points, bank=excluded.bank, "
        "value=excluded.value, event_transfers=excluded.event_transfers, event_transfers_cost=excluded.event_transfers_cost, "
        "retrieved_at=excluded.retrieved_at",
        (entry_id, event, data.get("active_chip"), history.get("points"), history.get("total_points"), history.get("bank"),
         history.get("value"), history.get("event_transfers"), history.get("event_transfers_cost"), at),
    )


def sync_leagues(conn: sqlite3.Connection, client: FPLApiAdapter | None = None, force: bool = False) -> dict:
    from fpl_agent.ingestion.my_team import get_my_team_entry_id

    entry_id = get_my_team_entry_id(conn)
    if entry_id is None:
        return {"status": "no_entry"}
    if not _due(conn, force):
        return {"status": "fresh"}
    client = client or FPLApiAdapter(timeout=30)
    at = _now()
    try:
        info = client.fetch_entry_info(entry_id).data
    except SourceFetchError as e:
        _logger.warning("league sync: entry fetch failed: %s", e)
        return {"status": "failed", "error": str(e)}

    leagues = (info.get("leagues") or {}).get("classic") or []
    tracked = []
    for lg in leagues:
        follow = lg.get("league_type") == "x" and (lg.get("rank_count") or 0) <= TRACK_MAX_ENTRIES
        conn.execute(
            "INSERT INTO fpl_league (id, name, league_type, rank_count, entry_rank, entry_last_rank, tracked, retrieved_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, league_type=excluded.league_type, "
            "rank_count=excluded.rank_count, entry_rank=excluded.entry_rank, entry_last_rank=excluded.entry_last_rank, "
            "tracked=excluded.tracked, retrieved_at=excluded.retrieved_at",
            (lg["id"], lg.get("name"), lg.get("league_type"), lg.get("rank_count"), lg.get("entry_rank"),
             lg.get("entry_last_rank"), int(follow), at),
        )
        if follow:
            tracked.append(lg)
    conn.commit()

    event = _latest_started_event(conn)
    rivals: set[int] = set()
    for lg in tracked:
        pages = {1}
        if lg.get("entry_rank"):
            pages.add((lg["entry_rank"] - 1) // PAGE_SIZE + 1)
        conn.execute("DELETE FROM fpl_league_standing WHERE league_id=?", (lg["id"],))
        for page in sorted(pages):
            try:
                data = client.fetch_league_standings(lg["id"], page).data
            except SourceFetchError as e:
                _logger.warning("league sync: standings %s p%s failed: %s", lg["id"], page, e)
                continue
            _store_standings(conn, lg["id"], (data.get("standings") or {}).get("results") or [], at)
            time.sleep(_PAUSE_SECONDS)
        conn.commit()
        rows = [dict(r) for r in conn.execute(
            "SELECT entry_id, rank FROM fpl_league_standing WHERE league_id=?", (lg["id"],),
        )]
        rivals.update(rivals_to_follow(rows, entry_id, lg.get("rank_count") or 0))

    fetched = 0
    if event is not None:
        have = {r["entry_id"] for r in conn.execute("SELECT entry_id FROM rival_event WHERE event=?", (event,))}
        for rival in sorted(rivals - have):
            try:
                data = client.fetch_entry_picks(rival, event).data
            except SourceFetchError as e:
                _logger.warning("league sync: picks %s GW%s failed: %s", rival, event, e)
                continue
            _store_picks(conn, rival, event, data, at)
            fetched += 1
            time.sleep(_PAUSE_SECONDS)
        conn.commit()

    conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (_META_KEY, at, at),
    )
    conn.commit()
    return {"status": "ok", "leagues": len(leagues), "tracked": len(tracked), "rivals": len(rivals), "picks_fetched": fetched, "event": event}
