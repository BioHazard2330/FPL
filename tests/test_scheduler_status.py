import subprocess

from fpl_agent.scheduler import status as status_mod
from fpl_agent.scheduler.status import check_scheduler_registered


def test_returns_none_when_task_not_registered(monkeypatch):
    monkeypatch.setattr(status_mod.sys, "platform", "win32")
    monkeypatch.setattr(
        status_mod.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="NOT_REGISTERED\n", stderr=""),
    )

    assert check_scheduler_registered("SomeTask") is None


def test_parses_real_task_info_when_registered(monkeypatch):
    monkeypatch.setattr(status_mod.sys, "platform", "win32")
    output = "State=Ready\nLastRunTime=11/30/1999 00:00:00\nNextRunTime=08/20/2026 20:48:42\nLastResult=267011\n"
    monkeypatch.setattr(
        status_mod.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=output, stderr=""),
    )

    info = check_scheduler_registered("SomeTask")

    assert info == {
        "State": "Ready", "LastRunTime": "11/30/1999 00:00:00",
        "NextRunTime": "08/20/2026 20:48:42", "LastResult": "267011",
    }


def test_returns_none_on_non_windows(monkeypatch):
    monkeypatch.setattr(status_mod.sys, "platform", "linux")

    assert check_scheduler_registered("SomeTask") is None


def test_returns_none_on_subprocess_timeout(monkeypatch):
    monkeypatch.setattr(status_mod.sys, "platform", "win32")

    def raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="powershell", timeout=15)

    monkeypatch.setattr(status_mod.subprocess, "run", raise_timeout)

    assert check_scheduler_registered("SomeTask") is None
