"""Stale-while-revalidate for the heavy screens.

A first visit to System, Market or Football used to wait 9-27s for its payload (and Command, My team and Plan for the
shared 6s context build), and a restart started every screen cold again. Each screen in `SNAPSHOT_SCREENS` now keeps its
last built JSON in memory and in `payload_snapshot`: a request is answered from the newest copy at once, and if that copy
is older than `FRESH_SECONDS` one background rebuild (single-flight per screen) replaces it, so the next poll (every screen
polls every 60s) gets the fresh one. A screen with no copy anywhere is built while the request waits, as before.

Served copies carry `_snapshot_age_seconds` so a client can tell. Parameterised payloads (a player, a club, a comparison)
and live-match payloads are never served this way."""
import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone

_logger = logging.getLogger("fpl_agent.payload_snapshots")

SNAPSHOT_SCREENS = frozenset({
    "command", "myteam", "plan", "football", "matchweek", "scout", "advanced", "receipts", "previews", "explorer", "signals",
})
FRESH_SECONDS = 90.0

_lock = threading.Lock()
_memory: dict[str, tuple[bytes, float]] = {}
_building: set[str] = set()


def _age_marked(body: bytes, built_epoch: float) -> bytes:
    """Re-serialise with the copy's age; bodies are dicts at the top level."""
    try:
        payload = json.loads(body)
    except ValueError:
        return body
    if isinstance(payload, dict):
        payload["_snapshot_age_seconds"] = round(time.time() - built_epoch, 1)
        return json.dumps(payload, default=str).encode("utf-8")
    return body


def _load_db(conn: sqlite3.Connection, screen: str) -> tuple[bytes, float] | None:
    try:
        row = conn.execute("SELECT body, built_at FROM payload_snapshot WHERE screen=?", (screen,)).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    try:
        built = datetime.fromisoformat(row["built_at"]).timestamp()
    except ValueError:
        return None
    return row["body"].encode("utf-8"), built


def _store(conn: sqlite3.Connection, screen: str, body: bytes, built: float, seconds: float) -> None:
    with _lock:
        _memory[screen] = (body, built)
    try:
        conn.execute(
            "INSERT INTO payload_snapshot (screen, body, built_at, build_seconds) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(screen) DO UPDATE SET body=excluded.body, built_at=excluded.built_at, build_seconds=excluded.build_seconds",
            (screen, body.decode("utf-8"), datetime.fromtimestamp(built, timezone.utc).isoformat(), round(seconds, 2)),
        )
        conn.commit()
    except sqlite3.OperationalError as exc:
        _logger.debug("snapshot write for %s skipped (%s); the memory copy stands", screen, exc)


def build_and_store(screen: str, build, conn_factory) -> bytes:
    started = time.time()
    conn = conn_factory()
    try:
        body = json.dumps(build(conn), default=str).encode("utf-8")
        _store(conn, screen, body, time.time(), time.time() - started)
        return body
    finally:
        conn.close()


def _rebuild_in_background(screen: str, build, conn_factory) -> None:
    with _lock:
        if screen in _building:
            return
        _building.add(screen)

    def run() -> None:
        try:
            build_and_store(screen, build, conn_factory)
        except Exception:
            _logger.exception("background rebuild of the %s payload failed; the last copy stays", screen)
        finally:
            with _lock:
                _building.discard(screen)

    threading.Thread(target=run, name=f"snapshot-{screen}", daemon=True).start()


def serve(screen: str, build, conn_factory) -> bytes:
    """The body for `screen`: the newest copy at once (rebuilding behind it when stale), or a fresh build when none exists.
    `build(conn)` returns the payload."""
    with _lock:
        mem = _memory.get(screen)
    copy = mem
    if copy is None:
        conn = conn_factory()
        try:
            copy = _load_db(conn, screen)
        finally:
            conn.close()
        if copy is not None:
            with _lock:
                _memory.setdefault(screen, copy)
    if copy is None:
        return build_and_store(screen, build, conn_factory)
    body, built = copy
    if time.time() - built > FRESH_SECONDS:
        _rebuild_in_background(screen, build, conn_factory)
        return _age_marked(body, built)
    return body


def clear_memory() -> None:
    with _lock:
        _memory.clear()
