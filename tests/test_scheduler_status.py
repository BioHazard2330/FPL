import subprocess

from click.testing import CliRunner

from fpl_agent.cli.main import cli
from fpl_agent.scheduler import status as status_mod
from fpl_agent.scheduler.status import check_scheduler_registered


def test_scheduler_status_cli_reports_both_real_daemon_tasks(monkeypatch):
    """Real gap fixed 2026-08-29 (restart-recovery audit): `fpl
    scheduler-status` used to only ever check FPLAgentSync, silently saying
    nothing about the real, separately-registered FPLAgentLivePoll task
    this project's own CLAUDE.md documents as required - confirmed live on
    the real dev machine that BOTH tasks are actually registered, but the
    status command only ever reported one of them."""
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(main_mod.sys, "platform", "win32")

    def fake_check(task_name):
        if task_name == "FPLAgentSync":
            return {"State": "Ready", "LastRunTime": "t1", "NextRunTime": "t2", "LastResult": "0"}
        return None  # FPLAgentLivePoll not registered on this test machine

    monkeypatch.setattr(main_mod, "check_scheduler_registered", fake_check)

    result = CliRunner().invoke(cli, ["scheduler-status"])

    assert result.exit_code == 0
    assert "FPLAgentSync" in result.output
    assert "FPLAgentLivePoll" in result.output
    assert "not registered" in result.output
    assert "setup_live_poll_scheduler.ps1" in result.output


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
