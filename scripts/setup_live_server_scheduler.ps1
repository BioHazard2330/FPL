<#
Registers a Windows Task Scheduler entry that keeps `fpl live-server`
running without any manual restart (2026-08-29, "live architecture
rebuild" milestone 2, spec section 13: "the user should only need to open
the dashboard"). `live-server` blocks forever by design (Ctrl+C to stop) -
this task's job is only to relaunch it if it ever exits (a crash, a
reboot) - `-MultipleInstances IgnoreNew` means a periodic re-trigger while
a real instance is still running is a safe, near-zero-cost no-op (the
real single-instance lock in `scheduler/process_lock.py`, same mechanism
`FPLAgentLivePoll` already uses, makes the second launch exit immediately).

Usage:
    powershell -ExecutionPolicy Bypass -File setup_live_server_scheduler.ps1 [-Port 8877] [-IntervalMinutes 5]

This makes a persistent, unattended change to the machine's Task Scheduler -
review before running. To remove it later, run remove_live_server_scheduler.ps1.
Separate from FPLAgentLivePoll (FotMob ingestion) and FPLAgentSync (the slow
sync cadence) - this task owns ONLY the real-time client transport
(`/events` SSE + static dashboard serving), per the spec's own explicit
"keep the worker persistent runtime and the dashboard/API separate"
allowance.
#>
param(
    [int]$Port = 8877,
    [int]$IntervalMinutes = 5,
    [string]$TaskName = "FPLAgentLiveServer"
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$FplExe = Join-Path $ProjectRoot ".venv\Scripts\fpl.exe"
$HiddenLauncher = Join-Path $PSScriptRoot "run_scheduled_hidden.vbs"

if (-not (Test-Path $FplExe)) {
    Write-Error "fpl.exe not found at $FplExe - run 'pip install -e .[dev]' in the project venv first."
    exit 1
}
if (-not (Test-Path $HiddenLauncher)) {
    Write-Error "run_scheduled_hidden.vbs not found at $HiddenLauncher - it should ship alongside this script."
    exit 1
}

$Action = New-ScheduledTaskAction -Execute "wscript.exe" `
    -Argument "`"$HiddenLauncher`" `"$FplExe`" `"live-server --port $Port`"" -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
# No ExecutionTimeLimit ceiling (0 = unlimited) - this task is meant to run
# forever, unlike FPLAgentSync's short-lived 10min-capped runs.
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew

try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
        -Description "fpl-agent: keeps the real-time SSE/dashboard transport (fpl live-server) running without manual restart" `
        -Force -ErrorAction Stop | Out-Null
} catch {
    Write-Error "Failed to register scheduled task '$TaskName': $_"
    exit 1
}

Write-Host "Registered scheduled task '$TaskName' - relaunches 'fpl live-server --port $Port' every $IntervalMinutes minutes if not already running."
Write-Host "Dashboard + real-time updates: http://127.0.0.1:$Port/dashboard.html"
Write-Host "Check status with: Get-ScheduledTask -TaskName $TaskName"
Write-Host "Remove with: powershell -ExecutionPolicy Bypass -File remove_live_server_scheduler.ps1"
