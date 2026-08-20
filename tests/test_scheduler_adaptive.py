import subprocess
import time

from fpl_agent.scheduler import adaptive as adaptive_mod
from fpl_agent.scheduler.adaptive import maybe_retighten_scheduler


def _insert_event(conn, hours_from_now):
    epoch = int(time.time() + hours_from_now * 3600)
    conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,is_current,is_next,"
        "average_entry_score,highest_score,updated_at) VALUES (1,'GW1','2026-01-01T00:00:00Z',?,0,0,0,0,NULL,NULL,'t0')",
        (epoch,),
    )
    conn.commit()


def test_noop_on_non_windows(db_conn, monkeypatch):
    monkeypatch.setattr(adaptive_mod.sys, "platform", "linux")

    assert maybe_retighten_scheduler(db_conn) is None


def test_noop_when_scheduler_not_registered(db_conn, monkeypatch):
    monkeypatch.setattr(adaptive_mod.sys, "platform", "win32")
    monkeypatch.setattr(adaptive_mod, "check_scheduler_registered", lambda: None)

    def _boom(*a, **k):
        raise AssertionError("must not attempt to re-register when nothing is registered")
    monkeypatch.setattr(adaptive_mod.subprocess, "run", _boom)

    assert maybe_retighten_scheduler(db_conn) is None


def test_noop_when_already_at_the_recommended_interval(db_conn, monkeypatch):
    monkeypatch.setattr(adaptive_mod.sys, "platform", "win32")
    monkeypatch.setattr(adaptive_mod, "check_scheduler_registered", lambda: {"State": "Ready"})
    _insert_event(db_conn, hours_from_now=50)  # -> moderate cadence, 60min
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('scheduler_interval_minutes','60','t0')"
    )
    db_conn.commit()

    def _boom(*a, **k):
        raise AssertionError("must not re-register when the interval already matches")
    monkeypatch.setattr(adaptive_mod.subprocess, "run", _boom)

    assert maybe_retighten_scheduler(db_conn) is None


def test_retightens_and_persists_the_new_interval_when_cadence_changed(db_conn, monkeypatch):
    monkeypatch.setattr(adaptive_mod.sys, "platform", "win32")
    monkeypatch.setattr(adaptive_mod, "check_scheduler_registered", lambda: {"State": "Ready"})
    _insert_event(db_conn, hours_from_now=1)  # -> deadline-day cadence, 15min
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('scheduler_interval_minutes','60','t0')"
    )
    db_conn.commit()

    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="Registered\n", stderr="")

    monkeypatch.setattr(adaptive_mod.subprocess, "run", _fake_run)

    result = maybe_retighten_scheduler(db_conn)

    assert result is not None
    assert "60" in result and "15" in result
    assert "-IntervalMinutes" in calls[0] and "15" in calls[0]
    row = db_conn.execute("SELECT value FROM app_meta WHERE key='scheduler_interval_minutes'").fetchone()
    assert row["value"] == "15"


def test_does_not_persist_when_reregistration_fails(db_conn, monkeypatch):
    monkeypatch.setattr(adaptive_mod.sys, "platform", "win32")
    monkeypatch.setattr(adaptive_mod, "check_scheduler_registered", lambda: {"State": "Ready"})
    _insert_event(db_conn, hours_from_now=1)  # -> 15min
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('scheduler_interval_minutes','60','t0')"
    )
    db_conn.commit()

    monkeypatch.setattr(
        adaptive_mod.subprocess, "run",
        lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="access denied"),
    )

    result = maybe_retighten_scheduler(db_conn)

    assert result is None
    row = db_conn.execute("SELECT value FROM app_meta WHERE key='scheduler_interval_minutes'").fetchone()
    assert row["value"] == "60"  # unchanged - a failed attempt must not claim success


def test_does_not_crash_on_subprocess_timeout(db_conn, monkeypatch):
    monkeypatch.setattr(adaptive_mod.sys, "platform", "win32")
    monkeypatch.setattr(adaptive_mod, "check_scheduler_registered", lambda: {"State": "Ready"})
    _insert_event(db_conn, hours_from_now=1)

    def _raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="powershell", timeout=30)
    monkeypatch.setattr(adaptive_mod.subprocess, "run", _raise_timeout)

    assert maybe_retighten_scheduler(db_conn) is None
