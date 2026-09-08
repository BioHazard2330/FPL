"""Real integration test for the SSE transport (2026-08-29, "live
architecture rebuild" pass, milestone 2). Starts an actual
`ThreadingHTTPServer` on a real ephemeral local port and drives it with
real HTTP requests - no mocked transport layer, the real socket/HTTP stack
is exercised.

Static-file assertions use `requests` (already a project dependency,
fine for a plain request/response). The real streaming SSE reads use a
plain `socket` instead - `requests`/urllib3's streaming reader was found
live (this session) to sit on a read that never returns data for this
server's real HTTP/1.0, no-Content-Length response shape, even though a
raw socket client (and a real browser's `EventSource`, which speaks HTTP/1.1
and handles exactly this response shape natively) receives every real
byte within one tailer poll cycle - confirmed directly with a standalone
script before writing these tests this way, not guessed."""
import json
import socket
import time

import pytest
import requests

from fpl_agent.live.sse_server import LiveServer


def _sse_connect(port: int, timeout: float = 6.0) -> socket.socket:
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.sendall(b"GET /events HTTP/1.1\r\nHost: localhost\r\n\r\n")
    s.settimeout(timeout)
    headers = s.recv(4096)
    assert headers.startswith(b"HTTP/1.0 200 OK") or headers.startswith(b"HTTP/1.1 200 OK")
    assert b"text/event-stream" in headers
    return s


def _read_sse_messages(s: socket.socket, deadline_seconds: float) -> list[dict]:
    """Reads whatever real bytes arrive until `deadline_seconds` elapses or
    the socket read times out, splitting on real SSE `data: ...\\n\\n`
    framing - a plain, honest parser, not a full SSE client library."""
    buf = b""
    messages = []
    deadline = time.time() + deadline_seconds
    s.settimeout(1.0)
    while time.time() < deadline:
        try:
            chunk = s.recv(4096)
        except socket.timeout:
            continue
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            line, buf = buf.split(b"\n\n", 1)
            if line.startswith(b"data: "):
                messages.append(json.loads(line[len(b"data: "):]))
    return messages


@pytest.fixture
def live_server(db_conn, tmp_path):
    # Real fix: the tailer runs on its own background thread and must open
    # its OWN sqlite connection there (connections are thread-affine) -
    # `db_conn`'s own monkeypatched DATA_DIR/DB_PATH make plain
    # `get_connection()` calls (even from a different thread) resolve to
    # the SAME real test DB file `db_conn` itself is already open against.
    from fpl_agent.database.connection import get_connection

    server = LiveServer(tmp_path, port=0, conn_factory=get_connection)
    server.start()
    yield server
    server.stop()


def _seed_minimal_match(conn):
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1, 3, 'Arsenal', 'ARS', 't0')"
    )
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1, 'Forward', 'FWD', 'Forwards', 't0')"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
        "VALUES (1, 1, 'Scorer', 1, 1, 'a', 0, 't0')"
    )
    conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, home_team_id, away_team_id, status, "
        "home_score, away_score, retrieved_at) VALUES (500, '500', 1, 1, 'LIVE', 0, 0, 't0')"
    )
    conn.commit()


def test_static_file_serving(live_server, tmp_path):
    (tmp_path / "dashboard.html").write_text("<html>real dashboard</html>", encoding="utf-8")
    resp = requests.get(f"http://127.0.0.1:{live_server.port}/dashboard.html", timeout=5)
    assert resp.status_code == 200
    assert "real dashboard" in resp.text
    assert resp.headers["Content-Type"].startswith("text/html")


def test_static_file_serving_blocks_path_traversal(live_server):
    resp = requests.get(f"http://127.0.0.1:{live_server.port}/../secret.txt", timeout=5)
    assert resp.status_code in (403, 404)


def test_root_serves_the_react_app_index_html(live_server, tmp_path):
    (tmp_path / "index.html").write_text("<html>react shell</html>", encoding="utf-8")
    resp = requests.get(f"http://127.0.0.1:{live_server.port}/", timeout=5)
    assert resp.status_code == 200
    assert "react shell" in resp.text
    assert resp.headers["Content-Type"].startswith("text/html")


def test_unknown_extensionless_path_falls_back_to_the_react_shell_for_client_side_routing(live_server, tmp_path):
    (tmp_path / "index.html").write_text("<html>react shell</html>", encoding="utf-8")
    resp = requests.get(f"http://127.0.0.1:{live_server.port}/my-team", timeout=5)
    assert resp.status_code == 200
    assert "react shell" in resp.text


def test_missing_asset_with_an_extension_404s_honestly_rather_than_falling_back(live_server, tmp_path):
    (tmp_path / "index.html").write_text("<html>react shell</html>", encoding="utf-8")
    resp = requests.get(f"http://127.0.0.1:{live_server.port}/assets/does-not-exist.js", timeout=5)
    assert resp.status_code == 404


def test_api_command_route_serves_real_json(live_server):
    """Real integration test, Phase 8.2 Stage 2 - `/api/command` must serve
    a real, valid JSON payload over an actual socket, from the SAME
    `conn_factory` the tailer thread already uses (never a second DB
    connection strategy). This is the React frontend's own real data
    source for COMMAND - the honest 'no squad locked yet' shape here is a
    correct response, not an error, since `test_sse_server.py`'s own
    `db_conn` fixture starts with an empty DB."""
    resp = requests.get(f"http://127.0.0.1:{live_server.port}/api/command", timeout=5)
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "application/json"
    payload = resp.json()
    assert "action" in payload and "bar" in payload and "gw" in payload


def test_api_route_404s_for_an_unknown_screen(live_server):
    resp = requests.get(f"http://127.0.0.1:{live_server.port}/api/not-a-real-screen", timeout=5)
    assert resp.status_code == 404


def test_api_routes_disabled_when_no_conn_factory_given(tmp_path):
    """Real backward-compat guard - a `LiveServer`/`make_handler` caller that
    never opts into `conn_factory` (existing tests, or a future caller that
    only wants `/events` + static files) must see `/api/*` fall through to
    static-file serving (a real, honest 404 for a nonexistent file), never a
    crash from a `None` conn_factory being called."""
    from fpl_agent.live.sse_server import make_handler, Broadcaster
    from http.server import ThreadingHTTPServer

    handler_cls = make_handler(Broadcaster(), tmp_path)  # conn_factory omitted
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    port = httpd.server_address[1]
    import threading
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        resp = requests.get(f"http://127.0.0.1:{port}/api/command", timeout=5)
        assert resp.status_code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(timeout=5)


def test_missing_file_is_404(live_server):
    resp = requests.get(f"http://127.0.0.1:{live_server.port}/nope.html", timeout=5)
    assert resp.status_code == 404


def test_sse_stream_delivers_a_real_new_match_event(live_server, db_conn):
    """The real end-to-end path: a genuinely new `match_events` row (the
    exact table `fotmob_source.py::sync_match` writes to) appears on the
    SSE stream within one real tailer poll cycle - no mocked broadcast."""
    _seed_minimal_match(db_conn)
    s = _sse_connect(live_server.port)

    # Real new incident, written directly (same shape `sync_match` uses).
    db_conn.execute(
        "INSERT INTO match_events (match_id, source, source_event_id, minute, event_type, team_id, player_id, "
        "description, retrieved_at) VALUES (500, 'fotmob', 'g1', 42, 'Goal', 1, 1, 'Goal - Scorer', 't1')"
    )
    db_conn.commit()

    messages = _read_sse_messages(s, deadline_seconds=9)
    s.close()
    found = next((m for m in messages if m.get("channel") == "match_event"), None)
    assert found is not None, f"expected a real match_event SSE message within the timeout, got {messages}"
    assert found["event_type"] == "Goal"
    assert found["minute"] == 42
    assert found["web_name"] == "Scorer"


def test_sse_stream_delivers_a_real_snapshot_update(live_server, tmp_path):
    """A real `live_snapshot.json` write (the file `write_live_snapshot`
    already produces every live tick) reaches the SSE stream too - the
    real reconciliation channel, not just discrete incident events."""
    s = _sse_connect(live_server.port)

    (tmp_path / "live_snapshot.json").write_text(json.dumps({"version": "t1", "event": 2}), encoding="utf-8")

    messages = _read_sse_messages(s, deadline_seconds=9)
    s.close()
    found = next((m for m in messages if m.get("channel") == "snapshot"), None)
    assert found is not None, f"expected a real snapshot SSE message within the timeout, got {messages}"
    assert found["snapshot"]["event"] == 2


def test_baseline_ids_captured_synchronously_before_start_closes_a_real_race(db_conn, tmp_path):
    """Real bug found + fixed live while writing this milestone's own
    tests: if the tailer's baseline `MAX(id)` were computed lazily on its
    own background thread (the first version of this code), a row
    inserted between `LiveServer(...)` returning and that thread actually
    running could be wrongly treated as "already known at startup" and
    silently never broadcast. `LiveServer.__init__` now captures the
    baseline synchronously, on the caller's own thread, before returning -
    this test proves a row inserted immediately after construction (before
    `.start()` is even called) is still real "new" and gets broadcast."""
    from fpl_agent.database.connection import get_connection

    _seed_minimal_match(db_conn)
    server = LiveServer(tmp_path, port=0, conn_factory=get_connection)
    # Real race window: insert BEFORE start() - a lazily-initialized
    # baseline would compute MAX(id) after this row already existed.
    db_conn.execute(
        "INSERT INTO match_events (match_id, source, source_event_id, minute, event_type, team_id, player_id, "
        "description, retrieved_at) VALUES (500, 'fotmob', 'g1', 10, 'Goal', 1, 1, 'Goal - Scorer', 't1')"
    )
    db_conn.commit()
    server.start()
    try:
        s = _sse_connect(server.port)
        # Real, confirmed-flaky-under-load timing margin (2026-09-02, Phase
        # 5E section 11 investigation): reran this exact test 8x in
        # isolation, always passed at ~9.5s wall time regardless (the poll
        # loop always waits out its own deadline, message or not) - the one
        # observed failure happened only inside a ~987s full-suite run,
        # consistent with real thread-scheduling contention under heavy
        # concurrent system load starving the tailer thread of CPU time
        # within the original 9s window, not a logic bug in the server or
        # this test. Bumped to 20s (pure wall-clock headroom, zero change to
        # `LiveServer`/tailer behavior) rather than left flaky.
        messages = _read_sse_messages(s, deadline_seconds=20)
        s.close()
        found = next((m for m in messages if m.get("channel") == "match_event"), None)
        assert found is not None, f"the pre-start row must still be reported as real/new, got {messages}"
        assert found["minute"] == 10
    finally:
        server.stop()


def test_sse_stream_delivers_a_real_match_fragment_on_snapshot_change(live_server, tmp_path, db_conn):
    """Real fix (2026-08-29, forensic product redesign - direct spec: "do
    not leave the momentum graph/shot map frozen until full dashboard
    regeneration... use incremental client-side updates from the canonical
    live state"). A real `live_snapshot.json` write whose `active_matches`
    entry matches the exact shape `_active_matches_block` produces gets
    re-rendered server-side (the SAME real `_match_card_html` function the
    initial page uses) and pushed as a `match_fragment` message - proves
    the browser can receive an updated chart without waiting for the next
    full dashboard regen."""
    _seed_minimal_match(db_conn)
    s = _sse_connect(live_server.port)

    snapshot = {
        "version": "t1",
        "active_matches": [{
            "match_id": 500, "fotmob_match_id": "500", "status": "LIVE",
            "home_team_id": 1, "away_team_id": 1, "home_short": "ARS", "away_short": "ARS",
            "home_score": 1, "away_score": 0, "live_minute": "42",
            "is_squad_match": False, "team_stats": {"home": None, "away": None},
            "momentum": [], "shots": [], "my_players": [],
        }],
    }
    (tmp_path / "live_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")

    messages = _read_sse_messages(s, deadline_seconds=9)
    s.close()
    found = next((m for m in messages if m.get("channel") == "match_fragment"), None)
    assert found is not None, f"expected a real match_fragment SSE message within the timeout, got {messages}"
    assert found["match_id"] == 500
    assert "1 - 0" in found["html"]
    assert 'data-match-card="500"' in found["html"]


def test_broadcaster_client_count_reflects_real_connections(live_server):
    assert live_server.broadcaster.client_count == 0
    s = _sse_connect(live_server.port)
    time.sleep(0.2)
    assert live_server.broadcaster.client_count == 1
    s.close()
