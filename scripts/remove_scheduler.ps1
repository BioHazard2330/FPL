<#
Removes the Windows Task Scheduler entry created by setup_scheduler.ps1.

Usage:
    powershell -ExecutionPolicy Bypass -File remove_scheduler.ps1
#>
param(
    [string]$TaskName = "FPLAgentSync"
)

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "No scheduled task named '$TaskName' found - nothing to remove."
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed scheduled task '$TaskName'."
