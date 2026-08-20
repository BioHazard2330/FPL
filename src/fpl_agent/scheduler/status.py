"""Real Windows Task Scheduler registration check - extracted so both
`fpl scheduler-status` and `fpl readiness` share one live check instead of
readiness hardcoding a static "not registered" string (a real bug found
2026-08-20: the user registered the scheduler mid-session and readiness kept
reporting it as unregistered, because that row had never actually checked
system state at all)."""
import subprocess
import sys

SCHEDULER_TASK_NAME = "FPLAgentSync"  # must match scripts/setup_scheduler.ps1's default


def check_scheduler_registered(task_name: str = SCHEDULER_TASK_NAME) -> dict | None:
    """Returns a dict with State/LastRunTime/NextRunTime/LastResult if the
    task is registered, or None if it isn't (or this isn't Windows) - never
    raises, since this is a status check, not a critical-path operation."""
    if sys.platform != "win32":
        return None

    ps_command = (
        f"$t = Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue; "
        f"if ($t) {{ $i = Get-ScheduledTaskInfo -TaskName '{task_name}'; "
        f"Write-Output \"State=$($t.State)\"; Write-Output \"LastRunTime=$($i.LastRunTime)\"; "
        f"Write-Output \"NextRunTime=$($i.NextRunTime)\"; Write-Output \"LastResult=$($i.LastTaskResult)\" }} "
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
