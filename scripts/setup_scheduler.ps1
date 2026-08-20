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
$HiddenLauncher = Join-Path $PSScriptRoot "run_scheduled_hidden.vbs"

if (-not (Test-Path $FplExe)) {
    Write-Error "fpl.exe not found at $FplExe - run 'pip install -e .[dev]' in the project venv first."
    exit 1
}
if (-not (Test-Path $HiddenLauncher)) {
    Write-Error "run_scheduled_hidden.vbs not found at $HiddenLauncher - it should ship alongside this script."
    exit 1
}

# Routed through wscript.exe + a tiny VBS launcher (see run_scheduled_hidden.vbs)
# instead of executing fpl.exe directly - a console-subsystem exe launched
# straight by Task Scheduler pops a visible command prompt every run, which
# was a real, reported annoyance (a window flashing open every 60 minutes
# showing raw CLI output). This suppresses that window entirely.
$Action = New-ScheduledTaskAction -Execute "wscript.exe" `
    -Argument "`"$HiddenLauncher`" `"$FplExe`" `"run-scheduled`"" -WorkingDirectory $ProjectRoot
# RepetitionDuration must be a valid ISO 8601 duration Task Scheduler's XML
# schema accepts - [TimeSpan]::MaxValue (~10,675,199 days) is NOT, and
# Register-ScheduledTask below throws on it while still falling through to
# the "success" messages (a non-terminating error, no try/catch here
# previously) - this silently registered NOTHING while claiming success,
# confirmed live the first time this script was ever actually run (it had
# only been syntax-checked before, never executed end to end). 3650 days
# (~10 years) is comfortably within the valid range and long enough that
# nobody will be running this exact task a decade from now anyway.
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew

try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
        -Description "fpl-agent: periodic FPL data sync + change detection + alerts (bootstrap spec sections 19-20)" `
        -Force -ErrorAction Stop | Out-Null
} catch {
    Write-Error "Failed to register scheduled task '$TaskName': $_"
    exit 1
}

Write-Host "Registered scheduled task '$TaskName' - runs 'fpl run-scheduled' every $IntervalMinutes minutes."
Write-Host "Check status with: fpl scheduler-status"
Write-Host "Remove with: powershell -ExecutionPolicy Bypass -File remove_scheduler.ps1"
