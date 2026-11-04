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
    monkeypatch.setattr(sse_server.RefreshJob, "_cycle_elsewhere", staticmethod(lambda: False))
    job = sse_server.RefreshJob()

    assert job.start() == "started"
    assert job.start() == "already_running"
    assert len(launched) == 1


class _Conn:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))

    def commit(self):
        pass

    def close(self):
        pass


def _serve_with_conn(tmp_path, conn):
    handler = make_handler(Broadcaster(), tmp_path, conn_factory=lambda: conn)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def test_made_transfer_records_every_move_then_replans_once_and_rolls_back_a_refused_set(tmp_path, monkeypatch):
    import fpl_agent.cli.main as cli_main
    from fpl_agent.ingestion import my_team
    from fpl_agent.live import payload_snapshots

    recorded, invalidated, replans = [], [], []

    def record(conn, out_id, in_id):
        if out_id == 99:
            raise ValueError("player 99 is not in the squad")
        recorded.append((out_id, in_id))
        return {"event": 9, "out": out_id, "in": in_id, "sale_tenths": 77, "cost_tenths": 67, "bank_tenths": 13}

    monkeypatch.setattr(my_team, "record_manual_transfer", record)
    monkeypatch.setattr(payload_snapshots, "invalidate", lambda conn, screens: invalidated.append(screens))
    monkeypatch.setattr(cli_main, "_maybe_trigger_week_plan_refresh", lambda conn: replans.append(1) or "squad changed")
    conn = _Conn()
    httpd, base = _serve_with_conn(tmp_path, conn)
    try:
        assert _post(f"{base}/api/made-transfer?moves=1:2,3:4")[0] == 404
        status, body = _post(f"{base}/api/made-transfer?moves=1:2,3:4", {"X-FPL-Refresh": "1"})
        assert status == 200 and body["status"] == "recorded" and len(body["moves"]) == 2
        assert recorded == [(1, 2), (3, 4)] and len(replans) == 1
        assert invalidated == [{"command", "myteam", "plan"}]

        status, body = _post(f"{base}/api/made-transfer?moves=5:6,99:7", {"X-FPL-Refresh": "1"})
        assert body["status"] == "refused" and "99" in body["reason"]
        assert any("DELETE FROM my_team_transfers" in sql and params == (9, 5, 6) for sql, params in conn.executed)
        assert len(replans) == 1
    finally:
        httpd.shutdown()


def test_a_cycle_this_server_did_not_start_reads_as_running_and_is_not_started_again(monkeypatch):
    monkeypatch.setattr(sse_server.RefreshJob, "_cycle_elsewhere", staticmethod(lambda: True))
    job = sse_server.RefreshJob()
    assert job.start() == "already_running"
    assert job.status()["running"] is True


def test_opening_the_page_starts_one_sync_and_a_reload_does_not_start_another(monkeypatch):
    class Conn:
        def close(self):
            pass

    class Job:
        starts = 0

        def start(self):
            Job.starts += 1
            return "started"

    from fpl_agent.scheduler import power_window

    monkeypatch.setattr(power_window, "gate_says_active", lambda now=None: False)
    monkeypatch.setattr(power_window, "last_successful_cycle", lambda conn: None)
    monkeypatch.setattr(sse_server, "_last_open_refresh", 0.0)
    now = 1_000_000.0
    assert sse_server.refresh_if_stale_on_open(Conn, now_epoch=now, job=Job()) == "started"
    assert sse_server.refresh_if_stale_on_open(Conn, now_epoch=now + 8, job=Job()) is None
    assert Job.starts == 1
    assert sse_server.refresh_if_stale_on_open(Conn, now_epoch=now + 1000, job=Job()) == "started"
