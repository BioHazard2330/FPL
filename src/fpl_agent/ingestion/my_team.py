"""Real "my team" tracking (2026-08-21) - the user gave a real FPL entry id
(7378572), a public identifier that needs no login to read: `/entry/{id}/`,
`/entry/{id}/history/`, `/entry/{id}/event/{gw}/picks/` are all official,
free, Tier 1 FPL API endpoints - the same ones Plan 1c's EO sampling already
uses via `FPLApiAdapter.fetch_entry_picks`. This is not the previously-
declined "FPL account login" scope (section 1.6/Phase 6's `mini-league` skip):
nothing here authenticates, submits, or writes back to the account - it's a
read of the same public data any FPL website already shows for that entry id.

Live-verified against the real entry (2026-08-21, preseason): `/entry/{id}/`
and `/entry/{id}/history/` both return real data right now (manager identity,
two real past-season summaries: 2024/25 rank 10,911,576, 2025/26 rank
1,000,697) - `/entry/{id}/event/1/picks/` currently 404s (GW1 hasn't locked
yet, deadline 2026-08-21T17:30:00Z) - the same time-gate this project already
documented for `fpl sync-eo`. Picks fetching follows the identical
event-lock guard `ingestion/eo_sample.py::sample_effective_ownership`
established rather than re-inventing it, and the picks JSON shape
(`entry_history` + `picks[]` with `element`/`position`/`multiplier`/
`is_captain`/`is_vice_captain`, `active_chip`) is the FPL API's well-
established, stable public schema - not yet live-exercised end-to-end for
THIS entry (no locked event exists yet this session), same disclosed
"deferred live verification" posture as sync-eo's own history."""
import sqlite3
from datetime import datetime, timezone

from fpl_agent.ingestion.fpl_api import FPLApiAdapter, SourceFetchError
from fpl_agent.ingestion.sync import update_source_health

SOURCE_NAME = "fpl_api_my_team"


def _latest_locked_event(conn: sqlite3.Connection) -> int | None:
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    row = conn.execute(
        "SELECT id FROM events WHERE deadline_time_epoch <= ? ORDER BY id DESC LIMIT 1",
        (now_epoch,),
    ).fetchone()
    return row["id"] if row else None


def _upsert_entry(conn: sqlite3.Connection, entry_id: int, info: dict, now: str) -> None:
    conn.execute(
        "INSERT INTO my_team_entry (entry_id, manager_name, region_name, favourite_team_id, "
        "joined_time, started_event, retrieved_at) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(entry_id) DO UPDATE SET manager_name=excluded.manager_name, "
        "region_name=excluded.region_name, favourite_team_id=excluded.favourite_team_id, "
        "joined_time=excluded.joined_time, started_event=excluded.started_event, "
        "retrieved_at=excluded.retrieved_at",
        (
            entry_id,
            f"{info.get('player_first_name', '')} {info.get('player_last_name', '')}".strip() or None,
            info.get("player_region_name"),
            info.get("favourite_team"),
            info.get("joined_time"),
            info.get("started_event"),
            now,
        ),
    )


def _upsert_season_history(conn: sqlite3.Connection, entry_id: int, past: list[dict], now: str) -> None:
    for row in past:
        conn.execute(
            "INSERT INTO my_team_season_history (entry_id, season_name, total_points, rank, "
            "rank_percentage, retrieved_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(entry_id, season_name) DO UPDATE SET total_points=excluded.total_points, "
            "rank=excluded.rank, rank_percentage=excluded.rank_percentage, retrieved_at=excluded.retrieved_at",
            (entry_id, row["season_name"], row.get("total_points"), row.get("rank"),
             row.get("rank_percentage"), now),
        )


def _upsert_gw_summary(conn: sqlite3.Connection, entry_id: int, current: list[dict], now: str) -> None:
    for row in current:
        conn.execute(
            "INSERT INTO my_team_gw_summary (entry_id, event, points, total_points, overall_rank, "
            "bank_tenths, team_value_tenths, event_transfers, event_transfers_cost, points_on_bench, "
            "retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(entry_id, event) DO UPDATE SET points=excluded.points, "
            "total_points=excluded.total_points, overall_rank=excluded.overall_rank, "
            "bank_tenths=excluded.bank_tenths, team_value_tenths=excluded.team_value_tenths, "
            "event_transfers=excluded.event_transfers, event_transfers_cost=excluded.event_transfers_cost, "
            "points_on_bench=excluded.points_on_bench, retrieved_at=excluded.retrieved_at",
            (
                entry_id, row["event"], row.get("points"), row.get("total_points"),
                row.get("overall_rank"), row.get("bank"), row.get("value"),
                row.get("event_transfers"), row.get("event_transfers_cost"),
                row.get("points_on_bench"), now,
            ),
        )


def _upsert_transfers(conn: sqlite3.Connection, entry_id: int, transfers: list[dict], now: str) -> int:
    """Real transfer log rows (2026-09-02, see `FPLApiAdapter.fetch_entry_transfers`'s
    own docstring for why this exists) - `INSERT OR IGNORE` against the real
    natural key so a re-sync of the full log (this endpoint has no
    incremental/since-param) never duplicates a transfer already stored."""
    n = 0
    for t in transfers:
        cur = conn.execute(
            "INSERT OR IGNORE INTO my_team_transfers (entry_id, event, element_in, element_in_cost, "
            "element_out, element_out_cost, transfer_time, retrieved_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                entry_id, t["event"], t["element_in"], t.get("element_in_cost"),
                t["element_out"], t.get("element_out_cost"), t["time"], now,
            ),
        )
        n += cur.rowcount
    return n


def _upsert_picks(conn: sqlite3.Connection, entry_id: int, event: int, payload: dict, now: str) -> int:
    active_chip = payload.get("active_chip")
    picks = payload.get("picks", [])
    conn.execute("DELETE FROM my_team_picks WHERE entry_id=? AND event=?", (entry_id, event))
    for p in picks:
        conn.execute(
            "INSERT INTO my_team_picks (entry_id, event, player_id, squad_slot, multiplier, "
            "is_captain, is_vice_captain, active_chip, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                entry_id, event, p["element"], p.get("position"), p.get("multiplier"),
                1 if p.get("is_captain") else 0, 1 if p.get("is_vice_captain") else 0,
                active_chip, now,
            ),
        )
    entry_history = payload.get("entry_history")
    if entry_history:
        _upsert_gw_summary(conn, entry_id, [entry_history], now)
    return len(picks)


def sync_my_team(conn: sqlite3.Connection, entry_id: int, event: int | None = None, force: bool = False) -> dict:
    """Real entry id -> real data, no login. `event` defaults to the latest
    locked gameweek; if none has locked yet (this preseason's actual state),
    picks are skipped with an honest reason rather than raising - entry info
    and season history are still fetched and saved regardless, since neither
    needs a locked event."""
    adapter = FPLApiAdapter()
    now = datetime.now(timezone.utc).isoformat()

    try:
        info = adapter.fetch_entry_info(entry_id).data
    except SourceFetchError as e:
        update_source_health(conn, SOURCE_NAME, success=False, error=str(e))
        raise
    _upsert_entry(conn, entry_id, info, now)

    history_error = None
    try:
        history = adapter.fetch_entry_history(entry_id).data
        _upsert_season_history(conn, entry_id, history.get("past", []), now)
        _upsert_gw_summary(conn, entry_id, history.get("current", []), now)
    except SourceFetchError as e:
        history_error = str(e)
    conn.commit()

    try:
        transfers = adapter.fetch_entry_transfers(entry_id).data
        _upsert_transfers(conn, entry_id, transfers, now)
        conn.commit()
    except SourceFetchError:
        pass  # non-fatal - the pending-window free-transfer count degrades to the pure history replay

    resolved_event = event if event is not None else _latest_locked_event(conn)
    picks_result = {"fetched": False, "event": resolved_event, "picks_count": 0, "reason": None}

    if resolved_event is None:
        picks_result["reason"] = "no gameweek has locked yet - picks aren't available"
    else:
        already = conn.execute(
            "SELECT COUNT(*) AS n FROM my_team_picks WHERE entry_id=? AND event=?", (entry_id, resolved_event)
        ).fetchone()["n"]
        if already and not force:
            picks_result = {"fetched": True, "event": resolved_event, "picks_count": already, "reason": "already synced"}
        else:
            try:
                payload = adapter.fetch_entry_picks(entry_id, resolved_event).data
                count = _upsert_picks(conn, entry_id, resolved_event, payload, now)
                conn.commit()
                picks_result = {"fetched": True, "event": resolved_event, "picks_count": count, "reason": None}
            except SourceFetchError as e:
                picks_result["reason"] = str(e)

    update_source_health(conn, SOURCE_NAME, success=history_error is None, error=history_error)

    return {
        "entry_id": entry_id,
        "manager_name": f"{info.get('player_first_name', '')} {info.get('player_last_name', '')}".strip(),
        "history_error": history_error,
        "picks": picks_result,
    }


def get_my_team_entry_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT value FROM app_meta WHERE key='my_team_entry_id'").fetchone()
    return int(row["value"]) if row else None


def set_my_team_entry_id(conn: sqlite3.Connection, entry_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('my_team_entry_id', ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (str(entry_id), now),
    )
    conn.commit()


def get_used_chips(conn: sqlite3.Connection, entry_id: int) -> set[str]:
    """Real chip names this entry has actually played, straight from the
    `active_chip` field on each synced picks row - closes a real gap
    disclosed in Plan 1b (`fpl season-sim --used-chips` previously had to be
    typed in by hand every time, since there's no live FPL account
    integration in this project). Not yet live-verified end to end (no
    locked event exists this session to have a real active_chip value to
    read), but the read path itself is real and tested against the same
    well-established schema `sync_my_team` already parses."""
    rows = conn.execute(
        "SELECT DISTINCT active_chip FROM my_team_picks WHERE entry_id=? AND active_chip IS NOT NULL",
        (entry_id,),
    ).fetchall()
    return {r["active_chip"] for r in rows}


def set_tracked_squad_ids(conn: sqlite3.Connection, player_ids: list[int]) -> None:
    """Real, cheap fallback source for `resolve_tracked_squad_ids` below,
    written by `fpl build-team`/`fpl build-squad` right after they've already
    computed a squad - zero extra compute. Same `app_meta` key-value pattern
    as `my_team_entry_id`/`total_players`/`scheduler_interval_minutes`. Not
    the ground truth (a real owned FPL squad is - see get_latest_squad) - a
    disclosed "last thing this project recommended/built" signal, used only
    when no real my-team squad exists yet (e.g. preseason, before GW1 locks
    and the user hasn't given an entry id, or the entry's picks haven't been
    synced for the current event)."""
    now = datetime.now(timezone.utc).isoformat()
    value = ",".join(str(pid) for pid in player_ids)
    conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('tracked_squad_ids', ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (value, now),
    )
    conn.commit()


def resolve_tracked_squad_ids(conn: sqlite3.Connection) -> set[int]:
    """The real squad this project's own live-alert layer scopes push
    notifications to (2026-08-21 live-gameweek layer) - deliberately narrow
    by design, not an oversight: alerting on every one of the ~390 players
    this project's Tier 2-4 sources cover would be exactly the "obnoxious"
    outcome the user explicitly asked this session to avoid. Resolution
    order, cheapest and most authoritative first, NEVER triggers a real
    ILP solve (that's `generate_build_team_report`'s own expensive job,
    wrong tool for a per-sync-cycle lookup):
    1. The real, currently-owned FPL squad (`get_latest_squad`), if a
       my-team entry id is saved AND that entry has synced picks for some
       real locked event - ground truth once it exists.
    2. The last squad `fpl build-team`/`fpl build-squad` actually built
       (`set_tracked_squad_ids`) - a real, disclosed fallback for the
       common preseason case where nothing has locked yet.
    Returns an empty set (never fabricates a squad) when neither source has
    ever been populated - callers must treat that as "nothing to scope
    alerts to yet," not an error."""
    entry_id = get_my_team_entry_id(conn)
    if entry_id is not None:
        latest = get_latest_squad(conn, entry_id)
        if latest is not None:
            return set(latest[1])
    row = conn.execute("SELECT value FROM app_meta WHERE key='tracked_squad_ids'").fetchone()
    if row and row["value"]:
        return {int(x) for x in row["value"].split(",") if x.strip()}
    return set()


def get_latest_squad(conn: sqlite3.Connection, entry_id: int) -> tuple[int, list[int]] | None:
    """Real squad ids for the most recent event this entry has stored picks
    for, plus that event number - `None` if no picks have ever been synced
    (e.g. still preseason, no event locked yet).

    Real, confirmed race fixed 2026-08-29 (direct user report: the dashboard
    "randomly" showed "no squad" with zero exception/warning trace, and
    refreshing the static HTML didn't help since it's only regenerated
    periodically). This used to be TWO separate `SELECT`s (`MAX(event)`,
    then picks `WHERE event=?`) - fine for a single-connection read, but
    this project runs a real concurrent writer (the Windows Task Scheduler's
    own `run-scheduled`/`_upsert_picks`, independent of any interactive
    session) against the same real `data/fpl.db`. `_upsert_picks` does a
    real `DELETE FROM my_team_picks WHERE entry_id=? AND event=?` followed by
    re-INSERTs for that same event (a resync) - two un-transacted `SELECT`s
    on a reader connection have no guarantee of seeing one consistent
    snapshot across both statements (`MAX(event)` could see event=N before
    the delete, the second `SELECT ... WHERE event=N` could then land inside
    the delete-to-reinsert gap and see zero rows) - a real torn read, not
    a `sqlite3.OperationalError` a `try/except` would ever catch, which is
    exactly why nothing was ever logged for it. Fixed by making this ONE
    real atomic statement (a scalar subquery for the max event) - SQLite
    guarantees a single statement's result reflects one consistent
    snapshot, so the two parts can never disagree with each other again."""
    rows = conn.execute(
        "SELECT event, player_id FROM my_team_picks WHERE entry_id=? "
        "AND event=(SELECT MAX(event) FROM my_team_picks WHERE entry_id=?) "
        "ORDER BY squad_slot",
        (entry_id, entry_id),
    ).fetchall()
    if not rows:
        return None
    return rows[0]["event"], [r["player_id"] for r in rows]


def get_latest_squad_detail(conn: sqlite3.Connection, entry_id: int) -> tuple[int, list[sqlite3.Row]] | None:
    """Same real, atomic scalar-subquery pattern as `get_latest_squad` above,
    extended to the full row (squad_slot/is_captain/is_vice_captain, not
    just player_id) - added 2026-08-29 to close a real, still-recurring
    residual race `get_latest_squad()`'s own 2026-08-29 fix didn't cover.

    `optimization.locked_squad.get_locked_squad` used to call
    `get_latest_squad()` (one atomic read) and THEN a second, separate
    `my_team_picks` query inside `_xi_from_real_picks` to get slot/captain
    detail - two independent un-transacted reads of the same table, with no
    guarantee the real concurrent writer (`run-scheduled`'s own
    `_upsert_picks` resync, DELETE-then-reinsert for one event) can't land
    in between. Confirmed live in production logs (2026-08-27/28): the
    exact warning `_xi_from_real_picks` added specifically to make this race
    loud ("my_team_picks now has zero rows for it - likely a concurrent
    resync landed between the two reads") fired repeatedly, roughly once
    per sync cycle - the race was diagnosed and logged, never actually
    closed. This function is the real close: ONE atomic statement returns
    everything `get_locked_squad` needs, so there is no second read left to
    race against."""
    rows = conn.execute(
        "SELECT event, player_id, squad_slot, is_captain, is_vice_captain FROM my_team_picks WHERE entry_id=? "
        "AND event=(SELECT MAX(event) FROM my_team_picks WHERE entry_id=?) "
        "ORDER BY squad_slot",
        (entry_id, entry_id),
    ).fetchall()
    if not rows:
        return None
    return rows[0]["event"], rows
