import json
import re
import sqlite3
from datetime import datetime, timezone

from fpl_agent.config import load_storage_budget
from fpl_agent.database.connection import get_connection, transaction
from fpl_agent.ingestion.change_detection import (
    detect_player_lifecycle_changes,
    detect_setpiece_changes,
    snapshot_player_state,
    snapshot_setpiece_state,
)
from fpl_agent.ingestion.fpl_api import FPLApiAdapter, SourceFetchError
from fpl_agent.ingestion.raw_store import prune_raw
from fpl_agent.normalization.fpl_core import (
    flatten_rules,
    normalize_element_types,
    normalize_events,
    normalize_fixtures,
    normalize_player_ownership,
    normalize_player_prices,
    normalize_player_setpieces,
    normalize_player_stats,
    normalize_players,
    normalize_teams,
)


class ValidationError(Exception):
    pass


def validate_bootstrap(raw: dict) -> None:
    teams = raw.get("teams", [])
    elements = raw.get("elements", [])
    if len(teams) != 20:
        raise ValidationError(f"expected 20 teams, got {len(teams)}")
    if len(elements) < 300:
        raise ValidationError(f"suspiciously few players: {len(elements)}")
    ids = [e["id"] for e in elements]
    if len(ids) != len(set(ids)):
        raise ValidationError("duplicate player ids in bootstrap")
    if not any(e.get("now_cost", 0) > 0 for e in elements):
        raise ValidationError("all player prices are zero — source anomaly")


def validate_fixtures(raw: list) -> None:
    if not raw:
        raise ValidationError("empty fixtures list")
    ids = [f["id"] for f in raw]
    if len(ids) != len(set(ids)):
        raise ValidationError("duplicate fixture ids")


def _extract_season(bootstrap: dict) -> str:
    url = bootstrap.get("game_config", {}).get("settings", {}).get("static_content_url", "")
    m = re.search(r"(\d{4})_(\d{2})", url)
    return f"{m.group(1)}-{m.group(2)}" if m else "unknown"


def _upsert_many(conn: sqlite3.Connection, table: str, rows: list[dict], now: str) -> None:
    if not rows:
        return
    data_cols = list(rows[0].keys())
    all_cols = data_cols + ["updated_at"]
    placeholders = ",".join(["?"] * len(all_cols))
    updates = ",".join(f"{c}=excluded.{c}" for c in all_cols if c != "id")
    sql = f"INSERT INTO {table} ({','.join(all_cols)}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {updates}"
    conn.executemany(sql, [tuple(r[c] for c in data_cols) + (now,) for r in rows])


def sync_price_history(conn: sqlite3.Connection, rows: list[dict], now: str) -> int:
    changed = 0
    for r in rows:
        pid = r["player_id"]
        cur = conn.execute(
            "SELECT id, value_tenths FROM player_price_history WHERE player_id=? AND valid_until IS NULL",
            (pid,),
        ).fetchone()
        if cur is None:
            conn.execute(
                "INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) VALUES (?,?,?,NULL)",
                (pid, r["value_tenths"], now),
            )
            changed += 1
        elif cur["value_tenths"] != r["value_tenths"]:
            conn.execute("UPDATE player_price_history SET valid_until=? WHERE id=?", (now, cur["id"]))
            conn.execute(
                "INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) VALUES (?,?,?,NULL)",
                (pid, r["value_tenths"], now),
            )
            changed += 1
    return changed


def sync_ownership_history(conn: sqlite3.Connection, rows: list[dict], now: str) -> int:
    changed = 0
    for r in rows:
        pid = r["player_id"]
        cur = conn.execute(
            "SELECT id, selected_by_percent FROM player_ownership_history WHERE player_id=? AND valid_until IS NULL",
            (pid,),
        ).fetchone()
        if cur is None:
            conn.execute(
                "INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) VALUES (?,?,?,NULL)",
                (pid, r["selected_by_percent"], now),
            )
            changed += 1
        elif cur["selected_by_percent"] != r["selected_by_percent"]:
            conn.execute("UPDATE player_ownership_history SET valid_until=? WHERE id=?", (now, cur["id"]))
            conn.execute(
                "INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) VALUES (?,?,?,NULL)",
                (pid, r["selected_by_percent"], now),
            )
            changed += 1
    return changed


_SETPIECE_FIELDS = ("penalties_order", "penalties_text", "corners_order", "corners_text", "direct_fk_order", "direct_fk_text")


def sync_setpiece_history(conn: sqlite3.Connection, rows: list[dict], now: str) -> int:
    changed = 0
    for r in rows:
        pid = r["player_id"]
        cur = conn.execute(
            f"SELECT id, {','.join(_SETPIECE_FIELDS)} FROM player_setpiece_history "
            "WHERE player_id=? AND valid_until IS NULL",
            (pid,),
        ).fetchone()
        new_tuple = tuple(r[f] for f in _SETPIECE_FIELDS)
        if cur is None:
            conn.execute(
                f"INSERT INTO player_setpiece_history (player_id, {','.join(_SETPIECE_FIELDS)}, valid_from, valid_until) "
                f"VALUES (?,{','.join(['?'] * len(_SETPIECE_FIELDS))},?,NULL)",
                (pid, *new_tuple, now),
            )
            changed += 1
        elif tuple(cur[f] for f in _SETPIECE_FIELDS) != new_tuple:
            conn.execute("UPDATE player_setpiece_history SET valid_until=? WHERE id=?", (now, cur["id"]))
            conn.execute(
                f"INSERT INTO player_setpiece_history (player_id, {','.join(_SETPIECE_FIELDS)}, valid_from, valid_until) "
                f"VALUES (?,{','.join(['?'] * len(_SETPIECE_FIELDS))},?,NULL)",
                (pid, *new_tuple, now),
            )
            changed += 1
    return changed


def sync_stats_snapshot(conn: sqlite3.Connection, rows: list[dict], retrieved_at: str) -> int:
    inserted = 0
    for r in rows:
        pid = r["player_id"]
        last = conn.execute(
            "SELECT stats_hash FROM player_stats_snapshot WHERE player_id=? ORDER BY retrieved_at DESC LIMIT 1",
            (pid,),
        ).fetchone()
        if last is None or last["stats_hash"] != r["stats_hash"]:
            cols = list(r.keys())
            all_cols = cols + ["retrieved_at"]
            placeholders = ",".join(["?"] * len(all_cols))
            conn.execute(
                f"INSERT INTO player_stats_snapshot ({','.join(all_cols)}) VALUES ({placeholders})",
                tuple(r[c] for c in cols) + (retrieved_at,),
            )
            inserted += 1
    return inserted


def sync_rules(conn: sqlite3.Connection, flat_rules: dict, season: str, source: str, effective_date: str) -> int:
    changed = 0
    for key, value in flat_rules.items():
        value_json = json.dumps(value, sort_keys=True)
        last = conn.execute(
            "SELECT version, value FROM rules WHERE rule_key=? AND season=? ORDER BY version DESC LIMIT 1",
            (key, season),
        ).fetchone()
        if last is None or last["value"] != value_json:
            next_version = 1 if last is None else last["version"] + 1
            conn.execute(
                "INSERT INTO rules (rule_key, season, version, effective_date, source, value) VALUES (?,?,?,?,?,?)",
                (key, season, next_version, effective_date, source, value_json),
            )
            changed += 1
    return changed


def update_source_health(
    conn: sqlite3.Connection,
    source_name: str,
    success: bool,
    latency_ms: int | None = None,
    error: str | None = None,
    parser_version: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute("SELECT source_name FROM source_health WHERE source_name=?", (source_name,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO source_health (source_name, last_success, last_failure, last_error, latency_ms, failure_count, parser_version) "
            "VALUES (?,?,?,?,?,?,?)",
            (source_name, now if success else None, None if success else now, error, latency_ms, 0 if success else 1, parser_version),
        )
    elif success:
        conn.execute(
            "UPDATE source_health SET last_success=?, latency_ms=?, failure_count=0, parser_version=? WHERE source_name=?",
            (now, latency_ms, parser_version, source_name),
        )
    else:
        conn.execute(
            "UPDATE source_health SET last_failure=?, last_error=?, failure_count=failure_count+1 WHERE source_name=?",
            (now, error, source_name),
        )
    conn.commit()


def run_sync() -> dict:
    adapter = FPLApiAdapter()
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()

    try:
        try:
            bootstrap_fetch = adapter.fetch_bootstrap()
        except SourceFetchError as e:
            update_source_health(conn, "fpl_api_bootstrap", success=False, error=str(e))
            raise
        validate_bootstrap(bootstrap_fetch.data)
        update_source_health(
            conn, "fpl_api_bootstrap", success=True,
            latency_ms=bootstrap_fetch.latency_ms, parser_version=bootstrap_fetch.parser_version,
        )

        try:
            fixtures_fetch = adapter.fetch_fixtures()
        except SourceFetchError as e:
            update_source_health(conn, "fpl_api_fixtures", success=False, error=str(e))
            raise
        validate_fixtures(fixtures_fetch.data)
        update_source_health(
            conn, "fpl_api_fixtures", success=True,
            latency_ms=fixtures_fetch.latency_ms, parser_version=fixtures_fetch.parser_version,
        )

        bootstrap = bootstrap_fetch.data

        # capture prior state before upserting, so change detection has something to diff against
        prev_player_state = snapshot_player_state(conn)
        prev_setpiece_state = snapshot_setpiece_state(conn)

        with transaction(conn):
            _upsert_many(conn, "teams", normalize_teams(bootstrap), now)
            _upsert_many(conn, "element_types", normalize_element_types(bootstrap), now)
            _upsert_many(conn, "events", normalize_events(bootstrap), now)
            new_player_rows = normalize_players(bootstrap)
            _upsert_many(conn, "players", new_player_rows, now)
            _upsert_many(conn, "fixtures", normalize_fixtures(fixtures_fetch.data), now)

            price_changed = sync_price_history(conn, normalize_player_prices(bootstrap), now)
            ownership_changed = sync_ownership_history(conn, normalize_player_ownership(bootstrap), now)
            stats_inserted = sync_stats_snapshot(conn, normalize_player_stats(bootstrap), now)

            new_setpiece_rows = normalize_player_setpieces(bootstrap)
            setpiece_changed = sync_setpiece_history(conn, new_setpiece_rows, now)

            lifecycle_events = detect_player_lifecycle_changes(
                conn, prev_player_state, new_player_rows, now, "fpl_api_bootstrap"
            )
            setpiece_events = detect_setpiece_changes(
                conn, prev_setpiece_state, new_setpiece_rows, now, "fpl_api_bootstrap"
            )

            season = _extract_season(bootstrap)
            rules_changed = sync_rules(conn, flatten_rules(bootstrap), season, "fpl_api_bootstrap", now)

        budget = load_storage_budget()
        pruned = prune_raw(budget.raw_retention_hours)

        return {
            "teams": len(bootstrap["teams"]),
            "players": len(bootstrap["elements"]),
            "fixtures": len(fixtures_fetch.data),
            "events": len(bootstrap["events"]),
            "price_changes": price_changed,
            "ownership_changes": ownership_changed,
            "stats_snapshots_inserted": stats_inserted,
            "setpiece_changes": setpiece_changed,
            "lifecycle_events": lifecycle_events,
            "setpiece_events": setpiece_events,
            "rules_changed": rules_changed,
            "season": season,
            "raw_files_pruned": pruned,
            "retrieved_at": now,
        }
    finally:
        conn.close()
