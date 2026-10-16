import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from fpl_agent.live import sse_server
from fpl_agent.live.sse_server import Broadcaster, make_handler


class _FakeJob:
    def __init__(self):
        self.started = 0

    def start(self):
        self.started += 1
        return "started"

    def status(self):
        return {"running": True, "started_at": "t", "finished_at": None, "returncode": None}


def _serve(tmp_path):
    handler = make_handler(Broadcaster(), tmp_path, conn_factory=lambda: None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _post(url, headers=None):
    req = urllib.request.Request(url, method="POST", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None


def test_refresh_needs_the_custom_header(tmp_path, monkeypatch):
    job = _FakeJob()
    monkeypatch.setattr(sse_server, "refresh_job", job)
    httpd, base = _serve(tmp_path)
    try:
        status, _ = _post(f"{base}/api/refresh")
        assert status == 404
        assert job.started == 0
    finally:
        httpd.shutdown()


def test_refresh_with_the_header_starts_one_job(tmp_path, monkeypatch):
    job = _FakeJob()
    monkeypatch.setattr(sse_server, "refresh_job", job)
    httpd, base = _serve(tmp_path)
    try:
        status, body = _post(f"{base}/api/refresh", {"X-FPL-Refresh": "1"})
        assert status == 200
        assert body["result"] == "started"
        assert job.started == 1
    finally:
        httpd.shutdown()


def test_other_post_paths_are_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(sse_server, "refresh_job", _FakeJob())
    httpd, base = _serve(tmp_path)
    try:
        status, _ = _post(f"{base}/api/command", {"X-FPL-Refresh": "1"})
        assert status == 404
    finally:
        httpd.shutdown()


def test_refresh_status_is_a_plain_get(tmp_path, monkeypatch):
    monkeypatch.setattr(sse_server, "refresh_job", _FakeJob())
    httpd, base = _serve(tmp_path)
    try:
        with urllib.request.urlopen(f"{base}/api/refresh-status", timeout=5) as r:
            assert json.loads(r.read())["running"] is True
    finally:
        httpd.shutdown()


def test_a_second_start_while_running_does_not_launch_another(monkeypatch):
    launched = []

    class _Proc:
        def poll(self):
            return None

    monkeypatch.setattr(sse_server.subprocess, "Popen", lambda *a, **k: launched.append(1) or _Proc())
    job = sse_server.RefreshJob()

    assert job.start() == "started"
    assert job.start() == "already_running"
    assert len(launched) == 1
