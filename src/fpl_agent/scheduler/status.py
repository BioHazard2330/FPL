"""Real Windows Task Scheduler registration check - extracted so both
`fpl scheduler-status` and `fpl readiness` share one live check instead of
readiness hardcoding a static "not registered" string (a real bug found
2026-08-20: the user registered the scheduler mid-session and readiness kept
reporting it as unregistered, because that row had never actually checked
system state at all).

2026-09-02 extension (autonomous-runtime audit, direct user report: real
optimizer runs silently stopped for ~40h while `fpl readiness` kept saying
"Scheduler OK"): the original check above only ever asked "is this task
REGISTERED, and what does Task Scheduler currently say its State/NextRunTime
are" - `State=Ready` is true both immediately after a healthy run AND after
a task has sat un-triggered (machine asleep, a hung prior instance holding
`scheduler/process_lock.py`'s lock, a crash) for days - it says nothing about
whether the task's `LastRunTime` is actually recent relative to its own real
registered cadence. `assess_task_health` below is the real fix: it reads the
task's own registered `Repetition.Interval` (the real cadence this project
already configured, never an invented number) and flags STALE/CRITICAL when
`LastRunTime` has fallen behind it by more than a two-miss tolerance (one
missed trigger can be a real transient - e.g. the machine was asleep - two in
a row is a genuine problem worth surfacing, not a false alarm)."""
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

SCHEDULER_TASK_NAME = "FPLAgentSync"  # must match scripts/setup_scheduler.ps1's default

# Every real autonomous task this project registers (scripts/setup_scheduler.ps1,
# setup_live_poll_scheduler.ps1, setup_live_server_scheduler.ps1) - kept here,
# not re-typed at each call site, so a new task only needs adding once.
ALL_TASK_NAMES = ("FPLAgentSync", "FPLAgentLivePoll", "FPLAgentLiveServer")


def check_scheduler_registered(task_name: str = SCHEDULER_TASK_NAME) -> dict | None:
    """Returns a dict with State/LastRunTime/NextRunTime/LastResult/
    IntervalMinutes if the task is registered, or None if it isn't (or this
    isn't Windows) - never raises, since this is a status check, not a
    critical-path operation. Timestamps are ISO 8601 (`.ToString("o")`) -
    unambiguous and locale-independent, unlike PowerShell's default
    `DateTime.ToString()` this used to emit."""
    if sys.platform != "win32":
        return None

    ps_command = (
        f"$t = Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue; "
        f"if ($t) {{ $i = Get-ScheduledTaskInfo -TaskName '{task_name}'; "
        f"Write-Output \"State=$($t.State)\"; "
        f"Write-Output \"LastRunTime=$($i.LastRunTime.ToString('o'))\"; "
        f"Write-Output \"NextRunTime=$($i.NextRunTime.ToString('o'))\"; "
        f"Write-Output \"LastResult=$($i.LastTaskResult)\"; "
        f"$rep = $t.Triggers[0].Repetition.Interval; "
        f"if ($rep) {{ Write-Output \"IntervalMinutes=$([System.Xml.XmlConvert]::ToTimeSpan($rep).TotalMinutes)\" }} }} "
        f"else {{ Write-Output 'NOT_REGISTERED' }}"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_command],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    output = result.stdout.strip()
    if not output or "NOT_REGISTERED" in output:
        return None

    parsed = {}
    for line in output.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            parsed[key.strip()] = value.strip()
    return parsed


@dataclass(frozen=True)
class TaskHealth:
    task_name: str
    status: str  # OK | STALE | CRITICAL | UNREGISTERED | UNKNOWN
    detail: str
    last_run_at: str | None
    age_minutes: float | None
    interval_minutes: float | None
    last_result: str | None


# A real, missed-trigger-tolerant multiplier, not an invented absolute
# number - one missed trigger (machine asleep, a long-running prior instance)
# is a real, non-alarming transient; two in a row genuinely means the task
# has stopped running, matching the ~40h-silent-optimizer incident this
# extension was built to catch (a 1h-interval task silently stops firing;
# 40h is ~40 missed triggers, nowhere near a false-positive risk at 2x).
_MISS_TOLERANCE = 2.0


def assess_task_health(task_name: str, info: dict | None = None) -> TaskHealth:
    """The real execution-freshness check `readiness.py`'s old "Scheduler"
    row never did - reads the task's OWN registered cadence (never a guess)
    and compares it against how long ago it actually last ran.

    `info` lets a caller that already has a fresh `check_scheduler_registered`
    result (e.g. `fpl scheduler-status`, which prints the raw fields too)
    pass it straight in rather than triggering a second real PowerShell
    subprocess call for the same task; omit it to have this function fetch
    its own."""
    if info is None:
        info = check_scheduler_registered(task_name)
    if info is None:
        return TaskHealth(
            task_name=task_name, status="UNREGISTERED",
            detail="not registered in Windows Task Scheduler",
            last_run_at=None, age_minutes=None, interval_minutes=None, last_result=None,
        )

    last_run_raw = info.get("LastRunTime")
    last_run_at = None
    age_minutes = None
    if last_run_raw and last_run_raw not in ("", "01/01/0001 00:00:00"):
        try:
            dt = datetime.fromisoformat(last_run_raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            last_run_at = dt.isoformat()
            age_minutes = (datetime.now(timezone.utc) - dt).total_seconds() / 60
        except ValueError:
            pass

    interval_minutes = None
    if info.get("IntervalMinutes"):
        try:
            interval_minutes = float(info["IntervalMinutes"])
        except ValueError:
            pass

    last_result = info.get("LastResult")
    state = info.get("State", "?")

    # Real, task-specific nuance (found live testing this function against
    # production): FPLAgentLiveServer is a PERSISTENT-process task, deliberately
    # re-triggered every 5min with `-MultipleInstances IgnoreNew` (see
    # setup_live_server_scheduler.ps1) so a still-running server makes the
    # periodic re-trigger a no-op - Task Scheduler reports THAT no-op as a
    # non-zero `LastResult` (0x800704C8/2147946720, "a new instance was
    # skipped"), which is the NORMAL, HEALTHY outcome for this one task, not
    # a failure. State=Running is the real signal for it; a generic
    # "nonzero LastResult = failed" read (correct for Sync/LivePoll, which
    # really do run-and-exit each trigger) would falsely flag a perfectly
    # healthy live server as STALE.
    if task_name == "FPLAgentLiveServer":
        if state == "Running":
            status = "OK"
            detail = "process running" + (f" (relaunch-checked {age_minutes:.0f}m ago)" if age_minutes is not None else "")
        elif age_minutes is not None and interval_minutes and age_minutes > interval_minutes * _MISS_TOLERANCE:
            status = "CRITICAL"
            detail = f"state={state}, last relaunch attempt {age_minutes:.0f}m ago - not recovering"
        else:
            status = "STALE"
            detail = f"state={state} - not currently running, awaiting next relaunch attempt"
        return TaskHealth(
            task_name=task_name, status=status, detail=detail,
            last_run_at=last_run_at, age_minutes=age_minutes,
            interval_minutes=interval_minutes, last_result=last_result,
        )

    # Real bug found live testing this against production (2026-09-02):
    # `LastResult=267009` (0x00041301, Windows' own documented
    # `SCHED_S_TASK_RUNNING`) showed up on FPLAgentLivePoll while it was
    # genuinely still executing (`State=Running`) - an informational
    # "currently running" code, not a failure, and not specific to any one
    # task's design the way LiveServer's IgnoreNew skip-code above is. Any
    # task can show this mid-run; treating it as `result_failed` would flag
    # a task as STALE for the crime of being caught mid-execution.
    _RUNNING_RESULT_CODES = {"267009", "267008"}  # SCHED_S_TASK_RUNNING, SCHED_S_TASK_QUEUED
    result_failed = last_result not in (None, "", "0", *_RUNNING_RESULT_CODES)

    if age_minutes is None:
        status = "UNKNOWN"
        detail = f"registered (state={state}) but has never run yet"
    elif interval_minutes and age_minutes > interval_minutes * _MISS_TOLERANCE:
        status = "CRITICAL"
        detail = (
            f"last run {age_minutes:.0f}m ago, expected every {interval_minutes:.0f}m "
            f"({age_minutes / interval_minutes:.1f}x overdue)"
        )
    elif result_failed:
        status = "STALE"
        detail = f"last run {age_minutes:.0f}m ago, exit code {last_result} (failed)"
    else:
        status = "OK"
        cadence = f", expected every {interval_minutes:.0f}m" if interval_minutes else ""
        started = "currently running, started" if state == "Running" else "last run"
        detail = f"{started} {age_minutes:.0f}m ago{cadence}"

    return TaskHealth(
        task_name=task_name, status=status, detail=detail,
        last_run_at=last_run_at, age_minutes=age_minutes,
        interval_minutes=interval_minutes, last_result=last_result,
    )


def assess_all_task_health() -> list[TaskHealth]:
    """Real health for every autonomous task this project registers - not
    just `FPLAgentSync`. `FPLAgentLiveServer` is a persistent-process task
    (meant to be State=Running most of the time, not fired-and-exited like
    the other two), so its own STALE/CRITICAL age math is less meaningful
    than its State - a caller that wants that distinction should read
    `check_scheduler_registered("FPLAgentLiveServer")["State"]` directly
    rather than only this generic per-task health."""
    return [assess_task_health(name) for name in ALL_TASK_NAMES]
