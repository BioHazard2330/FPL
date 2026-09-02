import subprocess
from datetime import datetime, timedelta, timezone

from click.testing import CliRunner

from fpl_agent.cli.main import cli
from fpl_agent.scheduler import status as status_mod
from fpl_agent.scheduler.status import assess_all_task_health, assess_task_health, check_scheduler_registered


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


def _mock_info(monkeypatch, task_name: str, info: dict | None):
    monkeypatch.setattr(
        status_mod, "check_scheduler_registered",
        lambda name=status_mod.SCHEDULER_TASK_NAME: info if name == task_name else None,
    )


def test_assess_task_health_flags_a_40h_stale_optimizer_task(monkeypatch):
    """Real regression for the direct user report this whole audit started
    from: optimizer runs stopped for ~40h while `fpl readiness` kept saying
    Scheduler OK, because the old check never compared LastRunTime against
    the task's own real registered cadence. FPLAgentSync's real registered
    interval is 60 minutes (see setup_scheduler.ps1's real PT1H trigger) -
    40h/60min = 40x overdue, nowhere near the 2x miss-tolerance."""
    stale = (datetime.now(timezone.utc) - timedelta(hours=40)).isoformat()
    _mock_info(monkeypatch, "FPLAgentSync", {
        "State": "Ready", "LastRunTime": stale, "NextRunTime": "2026-09-03T00:00:00+00:00",
        "LastResult": "0", "IntervalMinutes": "60",
    })

    health = assess_task_health("FPLAgentSync")

    assert health.status == "CRITICAL"
    assert "overdue" in health.detail


def test_assess_task_health_ok_when_within_cadence(monkeypatch):
    recent = (datetime.now(timezone.utc) - timedelta(minutes=12)).isoformat()
    _mock_info(monkeypatch, "FPLAgentSync", {
        "State": "Ready", "LastRunTime": recent, "NextRunTime": "2026-09-03T00:00:00+00:00",
        "LastResult": "0", "IntervalMinutes": "60",
    })

    health = assess_task_health("FPLAgentSync")

    assert health.status == "OK"


def test_assess_task_health_unregistered(monkeypatch):
    monkeypatch.setattr(status_mod, "check_scheduler_registered", lambda name=None: None)

    health = assess_task_health("FPLAgentSync")

    assert health.status == "UNREGISTERED"


def test_assess_task_health_live_server_running_is_ok_despite_nonzero_last_result(monkeypatch):
    """Real, task-specific nuance found live testing this against
    production: FPLAgentLiveServer's periodic relaunch-check reports a
    non-zero LastResult (0x800704C8, "a new instance was skipped") whenever
    the server is ALREADY running - the healthy, expected outcome for this
    one persistent-process task, never a failure the way it would be for
    FPLAgentSync/FPLAgentLivePoll."""
    recent = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    _mock_info(monkeypatch, "FPLAgentLiveServer", {
        "State": "Running", "LastRunTime": recent, "NextRunTime": "2026-09-03T00:00:00+00:00",
        "LastResult": "2147946720", "IntervalMinutes": "5",
    })

    health = assess_task_health("FPLAgentLiveServer")

    assert health.status == "OK"


def test_assess_task_health_live_server_not_running_and_overdue_is_critical(monkeypatch):
    stale = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    _mock_info(monkeypatch, "FPLAgentLiveServer", {
        "State": "Ready", "LastRunTime": stale, "NextRunTime": "2026-09-03T00:00:00+00:00",
        "LastResult": "1", "IntervalMinutes": "5",
    })

    health = assess_task_health("FPLAgentLiveServer")

    assert health.status == "CRITICAL"


def test_assess_task_health_running_with_scheduler_running_code_is_ok(monkeypatch):
    """Real bug found live testing against production: LastResult=267009
    (Windows' own SCHED_S_TASK_RUNNING) showed up on FPLAgentLivePoll while
    it was genuinely still executing - an informational "currently running"
    code, not a failure. Must never flag a mid-execution task as STALE."""
    just_started = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    _mock_info(monkeypatch, "FPLAgentLivePoll", {
        "State": "Running", "LastRunTime": just_started, "NextRunTime": "2026-09-03T00:00:00+00:00",
        "LastResult": "267009", "IntervalMinutes": "3",
    })

    health = assess_task_health("FPLAgentLivePoll")

    assert health.status == "OK"


def test_assess_task_health_still_flags_a_genuine_nonzero_failure_code(monkeypatch):
    recent = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    _mock_info(monkeypatch, "FPLAgentLivePoll", {
        "State": "Ready", "LastRunTime": recent, "NextRunTime": "2026-09-03T00:00:00+00:00",
        "LastResult": "1", "IntervalMinutes": "3",
    })

    health = assess_task_health("FPLAgentLivePoll")

    assert health.status == "STALE"
    assert "failed" in health.detail


def test_assess_all_task_health_covers_every_registered_task(monkeypatch):
    monkeypatch.setattr(status_mod, "check_scheduler_registered", lambda name: None)

    healths = assess_all_task_health()

    assert {h.task_name for h in healths} == set(status_mod.ALL_TASK_NAMES)
    assert all(h.status == "UNREGISTERED" for h in healths)
