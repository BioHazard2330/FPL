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
import inspect
import json
import logging
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

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
        self._broadcast_match_fragments(data)

    def _broadcast_match_fragments(self, data: dict) -> None:
        """Real fix (2026-08-29, forensic product redesign - direct spec:
        "do NOT leave the momentum graph/shot map frozen until full
        dashboard regeneration... use incremental client-side updates from
        the canonical live state"). `live_snapshot.json`'s own
        `active_matches` array (already broadcast above, raw) carries
        EXACTLY the same dict shape `match_centre.py::_match_card_html`
        renders from - re-rendering it here and pushing the resulting HTML
        means the browser gets a real, already-correct card fragment
        straight from the SAME Python function that builds the initial
        page, never a second (JS-reimplemented, and therefore divergence-
        prone) rendering path. Cheap: pure string formatting plus one
        already-small `match_events` LIMIT 10 read per match, at the same
        ~1.5s tailer cadence this class already runs at."""
        matches = data.get("active_matches") or []
        if not matches:
            return
        try:
            from fpl_agent.monitoring.dashboard.match_centre import _match_card_html
        except ImportError:
            return  # defensive only - never lets a rendering-layer import error kill the tailer loop
        for m in matches:
            try:
                html = _match_card_html(self.conn, m)
            except Exception:
                _logger.exception("live-server: failed to render match fragment for match_id=%s", m.get("match_id"))
                continue
            self.broadcaster.broadcast({
                "channel": "match_fragment", "match_id": m.get("match_id"), "html": html,
            })


def run_tailer_loop(tailer: DbTailer, stop_event: threading.Event, interval: float = _POLL_INTERVAL_SECONDS) -> None:
    while not stop_event.is_set():
        try:
            tailer.poll_once()
        except Exception:
            _logger.exception("live-server DB tailer poll failed - continuing, next tick will retry")
        stop_event.wait(interval)


def make_handler(broadcaster: Broadcaster, data_dir: Path, conn_factory=None) -> type[BaseHTTPRequestHandler]:
    """A fresh handler CLASS per server instance (closing over `broadcaster`/
    `data_dir`/`conn_factory`) - `http.server`'s own API requires a class,
    not an instance, for the handler factory.

    `conn_factory` (2026-09-08, Phase 8.2 Stage 2 - the React frontend's own
    JSON API) opens a fresh, short-lived, read-only-in-practice connection
    per `/api/<screen>` request - never the tailer's own long-lived
    connection, which stays on its own background thread per `LiveServer`'s
    existing thread-affinity rule. `None` (the default) disables the `/api/`
    routes entirely - existing callers that only ever wanted `/events` and
    static files (tests, `run_forever` without this new kwarg) see zero
    behavior change."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
            pass  # quiet by design - real operational logging goes through `_logger`, not stderr per request

        def do_GET(self) -> None:
            if self.path == "/events":
                self._serve_sse()
            elif self.path.startswith("/api/") and conn_factory is not None:
                self._serve_api()
            else:
                self._serve_static()

        def _serve_api(self) -> None:
            # Real, deliberate scope limit (2026-09-08, Phase 8.2 Stage 2) -
            # this endpoint ONLY shapes already-computed real data into JSON
            # (`monitoring.api.API_BUILDERS`, each builder a thin pass over
            # `DashboardContext`) - it never runs the optimizer, never
            # recomputes a decision. It does NOT call `build_dashboard_
            # context` directly - real, measured cost (~60s, see that
            # module's own docstring for the live-verified breakdown) means
            # every request must instead share ONE process-wide cached
            # context (`get_cached_dashboard_context`, default 60s TTL - the
            # same real regen cadence `fpl dashboard` already runs at), or a
            # naive per-request rebuild would make every page load/nav pay
            # the full real transfer-analysis + build-team-report cost this
            # project's own `generate_dashboard_html` was only ever meant to
            # pay once per periodic regen.
            from fpl_agent.monitoring.api import API_BUILDERS
            from fpl_agent.monitoring.dashboard.context import get_cached_dashboard_context

            raw = self.path.removeprefix("/api/")
            screen, _, query = raw.partition("?")
            screen = screen.strip("/")
            builder = API_BUILDERS.get(screen)
            if builder is None:
                self.send_error(404, f"no real API payload for '{screen}'")
                return

            # Real query-parameter support (2026-09-09). Every screen payload
            # up to this point answered one fixed question and needed no
            # arguments, so this dispatcher discarded the query string
            # outright. A club page and a player page are inherently
            # parameterised ("which club?"), and shipping every club and every
            # player in one payload is not a serious option - so a builder may
            # now opt in by declaring a `params` argument. Builders that do not
            # declare one are called exactly as before, unchanged.
            params = {k: v[0] for k, v in parse_qs(query).items() if v}
            conn = conn_factory()
            try:
                ctx = get_cached_dashboard_context(conn)
                if "params" in inspect.signature(builder).parameters:
                    payload = builder(ctx, params=params)
                else:
                    payload = builder(ctx)
            except LookupError as exc:
                # A real "no such club/player" - a 404, never a 500 and never
                # an empty-but-successful payload the browser would render as
                # a real profile full of blanks.
                self.send_error(404, str(exc))
                return
            except Exception:
                _logger.exception("building the '%s' API payload failed", screen)
                self.send_error(500, "payload build failed - see server log")
                return
            finally:
                conn.close()
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            # Real, deliberate wildcard (same posture as `/events` above -
            # read-only, unauthenticated, local-machine-only data).
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
            # Real, deliberate default flip (2026-09-08, Phase 8.2 Stage 2 -
            # direct user request: "turn off the old dashboard and keep this
            # new one as the main thing now"). `/` now serves the built
            # React app's `index.html` (`data/index.html`, deployed from
            # `frontend/dist/`) rather than the old Python-rendered
            # `dashboard.html` - which stays real, unchanged, and reachable
            # at its own explicit `/dashboard.html` path (any `ComingSoon`
            # screen's fallback link still works, and it's a real, honest
            # rollback path if the React app ever needs one).
            rel = self.path.lstrip("/").split("?", 1)[0] or "index.html"
            if ".." in rel:
                self.send_error(403)
                return
            target = data_dir / rel
            if not target.is_file():
                # Real SPA fallback: `react-router`'s client-side routes
                # (`/my-team`, `/plan`, ...) have no matching real file on
                # disk - a direct navigation or refresh on one of those
                # paths must still serve the React shell, which then
                # resolves the route client-side. Scoped to extension-less
                # paths only, so a genuinely missing asset (`/assets/x.js`)
                # still 404s honestly rather than silently serving HTML.
                if "." not in Path(rel).name:
                    target = data_dir / "index.html"
                if not target.is_file():
                    self.send_error(404)
                    return
            content_type = {
                ".html": "text/html; charset=utf-8", ".json": "application/json",
                ".js": "application/javascript; charset=utf-8", ".mjs": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
                ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf",
                ".ico": "image/x-icon", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
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
        handler_cls = make_handler(self.broadcaster, data_dir, conn_factory=self.conn_factory)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
        self.port = self.httpd.server_address[1]
        self._stop_event = threading.Event()
        self._tailer_thread: threading.Thread | None = None
        self._context_refresh_thread: threading.Thread | None = None
        self._readiness_refresh_thread: threading.Thread | None = None
        self._football_refresh_thread: threading.Thread | None = None
        self._scout_refresh_thread: threading.Thread | None = None
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
        # Real cache-warming + proactive refresh (2026-09-08, Phase 8.2 Stage
        # 2, extended Phase 9 - direct user requirement: "fix this lag...
        # I want it instantly"). The first `/api/<screen>` request after a
        # cold server start would otherwise pay the full real ~60-130s
        # `build_dashboard_context` cost itself (see that module's own
        # docstring). `_context_refresh_thread` warms the cache once
        # immediately, then keeps calling `run_context_refresh_loop` for the
        # server's whole lifetime - so after that one real boot-time cost, a
        # real user's request never pays it again (the cache is proactively
        # rebuilt every ~8 minutes, well inside the 10-minute TTL). Best-
        # effort only - a failure here is logged, never fatal to the server
        # itself (the tailer/SSE/static paths don't depend on this at all).
        self._context_refresh_thread = threading.Thread(target=self._context_refresh_main, daemon=True)
        self._context_refresh_thread.start()
        # Same real treatment for ADVANCED's own separate readiness cache
        # (`optimise_squad` inside `run_readiness_checks` is its own real
        # ~20s+ cost, confirmed live - not covered by the DashboardContext
        # cache above, so it needs its own boot warm + proactive refresh).
        self._readiness_refresh_thread = threading.Thread(target=self._readiness_refresh_main, daemon=True)
        self._readiness_refresh_thread.start()
        # Same real treatment for FOOTBALL's own separate league-wide signal
        # scan (~10-16s uncached, confirmed live - `build_football_payload`
        # never touched the DashboardContext cache above at all).
        self._football_refresh_thread = threading.Thread(target=self._football_refresh_main, daemon=True)
        self._football_refresh_thread.start()
        # Same real treatment for SCOUT's own Opportunity Board scan
        # (`find_breakouts`/`find_traps` etc.) - cached from the start this
        # time (Phase 9, learned from the football/advanced/command bugs).
        self._scout_refresh_thread = threading.Thread(target=self._scout_refresh_main, daemon=True)
        self._scout_refresh_thread.start()

    def _context_refresh_main(self) -> None:
        from fpl_agent.monitoring.dashboard.context import get_cached_dashboard_context, run_context_refresh_loop

        conn = self.conn_factory()
        try:
            get_cached_dashboard_context(conn)
        except Exception:
            _logger.exception("cache-warming build_dashboard_context failed - first real /api/ request will pay the full cost instead")
        finally:
            conn.close()
        run_context_refresh_loop(self.conn_factory, self._stop_event)

    def _readiness_refresh_main(self) -> None:
        from fpl_agent.monitoring.api.advanced_payload import _get_cached_readiness, run_readiness_refresh_loop
        from fpl_agent.optimization.locked_squad import get_locked_squad

        conn = self.conn_factory()
        try:
            locked = get_locked_squad(conn)
            squad_ids = set(locked.squad_ids) if locked is not None else set()
            _get_cached_readiness(conn, squad_ids)
        except Exception:
            _logger.exception("cache-warming readiness checks failed - first real ADVANCED-screen visit will pay the full cost instead")
        finally:
            conn.close()
        run_readiness_refresh_loop(self.conn_factory, self._stop_event)

    def _football_refresh_main(self) -> None:
        from fpl_agent.monitoring.api.football_payload import build_football_payload, run_football_refresh_loop
        from fpl_agent.monitoring.dashboard.context import get_cached_dashboard_context

        def ctx_factory():
            conn = self.conn_factory()
            try:
                return get_cached_dashboard_context(conn)
            finally:
                conn.close()

        try:
            build_football_payload(ctx_factory())
        except Exception:
            _logger.exception("cache-warming the football payload failed - first real FOOTBALL-screen visit will pay the full cost instead")
        run_football_refresh_loop(ctx_factory, self._stop_event)

    def _scout_refresh_main(self) -> None:
        from fpl_agent.monitoring.api.scout_payload import build_scout_payload, run_scout_refresh_loop
        from fpl_agent.monitoring.dashboard.context import get_cached_dashboard_context

        def ctx_factory():
            conn = self.conn_factory()
            try:
                return get_cached_dashboard_context(conn)
            finally:
                conn.close()

        try:
            build_scout_payload(ctx_factory())
        except Exception:
            _logger.exception("cache-warming the scout payload failed - first real SCOUT-screen visit will pay the full cost instead")
        run_scout_refresh_loop(ctx_factory, self._stop_event)

    def stop(self) -> None:
        self._stop_event.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._tailer_thread is not None:
            self._tailer_thread.join(timeout=5)
        if self._server_thread is not None:
            self._server_thread.join(timeout=5)
        if self._context_refresh_thread is not None:
            self._context_refresh_thread.join(timeout=5)
        if self._readiness_refresh_thread is not None:
            self._readiness_refresh_thread.join(timeout=5)
        if self._football_refresh_thread is not None:
            self._football_refresh_thread.join(timeout=5)
        if self._scout_refresh_thread is not None:
            self._scout_refresh_thread.join(timeout=5)


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
