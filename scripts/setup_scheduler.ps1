<#
Registers a Windows Task Scheduler entry running `fpl run-scheduled` periodically
(sections 19-20: durable OS scheduler, not a permanent Claude session, as the
season-long backend). `run-scheduled` itself does the resource-aware defer check
(section 21) - this script just decides how often to knock.

Usage:
    powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1 [-IntervalMinutes 60]

This makes a persistent, unattended change to the machine's Task Scheduler -
review before running. To remove it later, run remove_scheduler.ps1.
#>
param(
    [int]$IntervalMinutes = 60,
    [string]$TaskName = "FPLAgentSync"
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$FplExe = Join-Path $ProjectRoot ".venv\Scripts\fpl.exe"

if (-not (Test-Path $FplExe)) {
    Write-Error "fpl.exe not found at $FplExe - run 'pip install -e .[dev]' in the project venv first."
    exit 1
}

$Action = New-ScheduledTaskAction -Execute $FplExe -Argument "run-scheduled" -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration ([TimeSpan]::MaxValue)
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description "fpl-agent: periodic FPL data sync + change detection + alerts (bootstrap spec sections 19-20)" `
    -Force

Write-Host "Registered scheduled task '$TaskName' - runs 'fpl run-scheduled' every $IntervalMinutes minutes."
Write-Host "Check status with: fpl scheduler-status"
Write-Host "Remove with: powershell -ExecutionPolicy Bypass -File remove_scheduler.ps1"
