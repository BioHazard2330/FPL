"""Real-time client transport (2026-08-29, "live architecture rebuild" pass,
milestone 2 - direct spec: "replace the browser-as-primary-poller model
with SSE ... the browser applies only the changed state"). A real,
stdlib-only Server-Sent-Events endpoint plus static file serving - no new
dependency, no paid service.

Real cross-process constraint this module exists to solve: `live-match-
poll` (the process that actually calls FotMob/writes real events) and this
server are two SEPARATE real OS processes - milestone 1's in-process
`EventBus` singleton does not span them. Rather than adding real
inter-process infrastructure (a socket, a message broker - real complexity
this single-laptop, free-resources project doesn't need), `DbTailer` tails
the SAME real, already-persisted append-only tables
(`match_events`/`change_events`) and the already-written
`live_snapshot.json` file, translating each genuinely NEW row/version into
a real SSE push. This is also, by construction, the real reconciliation
mechanism the spec asks for (section 9) - every push is read straight from
the authoritative DB/file state, never an in-memory-only fact that could
drift from it.

The browser's existing ~10s `live_snapshot.json` poll (`assemble.py`) is
UNCHANGED by this module - it keeps running as the real fallback/
reconciliation path per the spec's own "this is the fallback, not the
primary" instruction. SSE is additive: when this server is reachable, real
updates arrive close to immediately; when it isn't (not started, or a
dashboard opened without it), the existing poll continues working exactly
as before - zero regression risk."""
import json
import logging
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_logger = logging.getLogger("fpl_agent.live_server")

_POLL_INTERVAL_SECONDS = 1.5
_KEEPALIVE_SECONDS = 15


class Broadcaster:
    """One real, in-memory fan-out point per running `live-server` process -
    every connected browser tab gets its own queue; a broadcast reaches all
    of them. Thread-safe (the HTTP server is threaded - each SSE connection
    is its own thread)."""

    def __init__(self) -> None:
        self._clients: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def register(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._clients.add(q)
        return q

    def unregister(self, q: queue.Queue) -> None:
        with self._lock:
            self._clients.discard(q)

    def broadcast(self, message: dict) -> None:
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            q.put(message)

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)


class DbTailer:
    """Real, cheap, read-only polling of already-persisted state - never
    recomputes anything, never touches the optimizer. `conn` is this
    server's own real, long-lived connection (a fresh `get_connection()`,
    never the ingestion side's)."""

    def __init__(
        self, conn, snapshot_path: Path, broadcaster: Broadcaster,
        initial_match_event_id: int | None = None, initial_change_event_id: int | None = None,
    ) -> None:
        self.conn = conn
        self.snapshot_path = snapshot_path
        self.broadcaster = broadcaster
        # Real startup-race fix (2026-08-29, found live by this milestone's
        # own test): a genuinely new row inserted between "the server
        # started" and "the tailer thread got around to computing its own
        # baseline" would be wrongly treated as already-known (baseline
        # computed AFTER it existed) and silently never broadcast.
        # `LiveServer.__init__` now computes these baselines synchronously,
        # on the constructing thread, BEFORE the tailer thread (or any real
        # caller) can possibly observe a later row - passed in here rather
        # than re-derived on the tailer's own thread, which could already
        # be too late.
        self._last_match_event_id = (
            initial_match_event_id if initial_match_event_id is not None else self._max_id("match_events")
        )
        self._last_change_event_id = (
            initial_change_event_id if initial_change_event_id is not None else self._max_id("change_events")
        )
        self._last_snapshot_mtime: float | None = None

    def _max_id(self, table: str) -> int:
        row = self.conn.execute(f"SELECT MAX(id) AS m FROM {table}").fetchone()
        return row["m"] or 0

    def poll_once(self) -> None:
        self._poll_match_events()
        self._poll_change_events()
        self._poll_snapshot()

    def _poll_match_events(self) -> None:
        rows = self.conn.execute(
            "SELECT me.id, me.match_id, me.event_type, me.minute, me.description, me.player_id, p.web_name "
            "FROM match_events me LEFT JOIN players p ON p.id = me.player_id "
            "WHERE me.id > ? ORDER BY me.id", (self._last_match_event_id,),
        ).fetchall()
        for r in rows:
            self._last_match_event_id = r["id"]
            self.broadcaster.broadcast({
                "channel": "match_event", "id": r["id"], "match_id": r["match_id"], "event_type": r["event_type"],
                "minute": r["minute"], "description": r["description"],
                "player_id": r["player_id"], "web_name": r["web_name"],
            })

    def _poll_change_events(self) -> None:
        # Real LEFT JOIN onto players (2026-08-29, milestone 5) - the SAME
        # real join `live_snapshot.py::_recent_changes_block` already uses
        # for the poll-based feed, so the browser's `humanizeChangeEvent`
        # can render a real player name here too, not just "player 123".
        # `NULL` for a non-player entity (e.g. a real `fixture` kickoff
        # reminder) - never fabricated.
        rows = self.conn.execute(
            "SELECT ce.id, ce.event_type, ce.entity, ce.entity_id, ce.old_value, ce.new_value, ce.severity, "
            "ce.detected_at, p.web_name FROM change_events ce LEFT JOIN players p ON p.id = ce.entity_id "
            "WHERE ce.id > ? ORDER BY ce.id", (self._last_change_event_id,),
        ).fetchall()
        for r in rows:
            self._last_change_event_id = r["id"]
            self.broadcaster.broadcast({
                "channel": "change_event", "event_type": r["event_type"], "entity": r["entity"],
                "entity_id": r["entity_id"], "old_value": r["old_value"], "new_value": r["new_value"],
                "severity": r["severity"], "detected_at": r["detected_at"], "web_name": r["web_name"],
            })

    def _poll_snapshot(self) -> None:
        if not self.snapshot_path.exists():
            return
        mtime = self.snapshot_path.stat().st_mtime
        if mtime == self._last_snapshot_mtime:
            return
        self._last_snapshot_mtime = mtime
        try:
            data = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return  # real, transient - a write in progress; the next tick re-reads
        self.broadcaster.broadcast({"channel": "snapshot", "snapshot": data})


def run_tailer_loop(tailer: DbTailer, stop_event: threading.Event, interval: float = _POLL_INTERVAL_SECONDS) -> None:
    while not stop_event.is_set():
        try:
            tailer.poll_once()
        except Exception:
            _logger.exception("live-server DB tailer poll failed - continuing, next tick will retry")
        stop_event.wait(interval)


def make_handler(broadcaster: Broadcaster, data_dir: Path) -> type[BaseHTTPRequestHandler]:
    """A fresh handler CLASS per server instance (closing over `broadcaster`/
    `data_dir`) - `http.server`'s own API requires a class, not an instance,
    for the handler factory."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
            pass  # quiet by design - real operational logging goes through `_logger`, not stderr per request

        def do_GET(self) -> None:
            if self.path == "/events":
                self._serve_sse()
            else:
                self._serve_static()

        def _serve_sse(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            # Real, deliberate wildcard (2026-08-29) - this is read-only,
            # unauthenticated, local-machine-only data (the same real
            # snapshot already served over plain, uncredentialed HTTP by
            # this same handler's static-file branch); lets the dashboard
            # be opened from a different local port/origin than this
            # server's own, without CORS blocking `EventSource`.
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            q = broadcaster.register()
            try:
                while True:
                    try:
                        item = q.get(timeout=_KEEPALIVE_SECONDS)
                    except queue.Empty:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        continue
                    self.wfile.write(f"data: {json.dumps(item)}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass  # real, expected - the browser tab closed or navigated away
            finally:
                broadcaster.unregister(q)

        def _serve_static(self) -> None:
            rel = self.path.lstrip("/") or "dashboard.html"
            if ".." in rel:
                self.send_error(403)
                return
            target = data_dir / rel
            if not target.is_file():
                self.send_error(404)
                return
            content_type = {
                ".html": "text/html; charset=utf-8", ".json": "application/json",
            }.get(target.suffix, "application/octet-stream")
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


class LiveServer:
    """Owns the real HTTP server + tailer thread together so a caller (the
    CLI command, or a test) can start/stop both as one unit.

    Real fix (found by this milestone's own integration test): sqlite3
    connections are thread-affine by default (`check_same_thread=True`) -
    the tailer runs on its own real background thread, so it must open ITS
    OWN real connection there via `conn_factory` (defaulting to this
    project's own `get_connection()`), never reuse a connection created on
    the caller's thread."""

    def __init__(self, data_dir: Path, port: int = 0, conn_factory=None) -> None:
        from fpl_agent.database.connection import get_connection as _get_connection

        self.data_dir = data_dir
        self.conn_factory = conn_factory or _get_connection
        self.broadcaster = Broadcaster()
        handler_cls = make_handler(self.broadcaster, data_dir)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
        self.port = self.httpd.server_address[1]
        self._stop_event = threading.Event()
        self._tailer_thread: threading.Thread | None = None
        self._server_thread: threading.Thread | None = None
        self._tailer_conn = None
        # Real startup-race fix (see `DbTailer.__init__`'s own docstring) -
        # captured synchronously, right here on the constructing thread,
        # BEFORE `start()` spins up the tailer thread - a short-lived
        # connection used only to read two real MAX(id) values, closed
        # immediately after.
        baseline_conn = self.conn_factory()
        try:
            self._initial_match_event_id = baseline_conn.execute(
                "SELECT MAX(id) AS m FROM match_events"
            ).fetchone()["m"] or 0
            self._initial_change_event_id = baseline_conn.execute(
                "SELECT MAX(id) AS m FROM change_events"
            ).fetchone()["m"] or 0
        finally:
            baseline_conn.close()

    def _tailer_main(self) -> None:
        self._tailer_conn = self.conn_factory()
        tailer = DbTailer(
            self._tailer_conn, self.data_dir / "live_snapshot.json", self.broadcaster,
            initial_match_event_id=self._initial_match_event_id,
            initial_change_event_id=self._initial_change_event_id,
        )
        run_tailer_loop(tailer, self._stop_event)
        self._tailer_conn.close()

    def start(self) -> None:
        self._tailer_thread = threading.Thread(target=self._tailer_main, daemon=True)
        self._tailer_thread.start()
        self._server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._server_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._tailer_thread is not None:
            self._tailer_thread.join(timeout=5)
        if self._server_thread is not None:
            self._server_thread.join(timeout=5)


def run_forever(data_dir: Path, port: int, conn_factory=None) -> None:
    """The real CLI entry point (`fpl live-server`) - blocks until
    Ctrl+C/KeyboardInterrupt, then shuts down cleanly."""
    import time

    server = LiveServer(data_dir, port=port, conn_factory=conn_factory)
    server.start()
    _logger.info("live-server listening on http://127.0.0.1:%d (SSE at /events)", server.port)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
