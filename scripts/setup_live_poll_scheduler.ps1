<#
Registers a Windows Task Scheduler entry that keeps `fpl live-match-poll`
running without any manual restart (matchday-autonomy pass, 2026-08-22 -
section 40/48's "no manual live-watch restart" / "start the system once and
leave it" requirement). `live-match-poll` itself already stops cleanly once
nothing is tracked (idle exit, not a bug) or after --max-hours - this task's
job is only to relaunch it periodically so a real matchday is never missed
just because a prior run already exited. `-MultipleInstances IgnoreNew`
means a periodic re-trigger while an instance is still genuinely mid-match
is a safe no-op, not a duplicate poller.

Usage:
    powershell -ExecutionPolicy Bypass -File setup_live_poll_scheduler.ps1 [-IntervalMinutes 30] [-MaxHours 6]

This makes a persistent, unattended change to the machine's Task Scheduler -
review before running. To remove it later, run remove_live_poll_scheduler.ps1.
Separate from `setup_scheduler.ps1`/`FPLAgentSync` (slow-cadence data sync) -
this project's single authoritative match-lifecycle logic
(auto-discovery/live polling/FULL_TIME finalization) lives in one place
(`models/match_discovery.py`, `ingestion/fotmob_source.py`) either way; this
task and FPLAgentSync are just two different cadences calling into it.
#>
param(
    [int]$IntervalMinutes = 30,
    [double]$MaxHours = 6.0,
    [string]$TaskName = "FPLAgentLivePoll"
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
    -Argument "`"$HiddenLauncher`" `"$FplExe`" `"live-match-poll --max-hours $MaxHours`"" -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
# ExecutionTimeLimit set to MaxHours+buffer, not the short 10min used by
# FPLAgentSync's own task - this one is a real long-running poller by design.
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Hours ($MaxHours + 0.5)) -MultipleInstances IgnoreNew

try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
        -Description "fpl-agent: keeps fast live-match polling running without manual restart" `
        -Force -ErrorAction Stop | Out-Null
} catch {
    Write-Error "Failed to register scheduled task '$TaskName': $_"
    exit 1
}

Write-Host "Registered scheduled task '$TaskName' - relaunches 'fpl live-match-poll --max-hours $MaxHours' every $IntervalMinutes minutes if not already running."
Write-Host "Check status with: Get-ScheduledTask -TaskName $TaskName"
Write-Host "Remove with: powershell -ExecutionPolicy Bypass -File remove_live_poll_scheduler.ps1"
