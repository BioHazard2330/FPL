<#
Places a real Windows Shortcut (.lnk) in the current user's own Startup
folder (`shell:startup`) pointing at `startup_trigger_hidden.vbs` (2026-08-29,
direct user requirement: "even if i shut down my laptop and the next day i
turn it on, everything starts automatically with no issues"). See
startup_trigger.ps1's own docstring for the full real reasoning - this is
the non-elevated path to "start everything at login" after a genuine,
confirmed platform gap ruled out the cleaner fix (an `AtLogOn` scheduled-
task trigger needs Administrator rights to register, even for a task you
already own).

Writing to a user's own Startup folder never needs admin rights - this
script is safe to run from a normal, non-elevated PowerShell session (unlike
the setup_*_scheduler.ps1 scripts, which register the underlying scheduled
tasks themselves and only need to be run once, ever, per machine).

Usage:
    powershell -ExecutionPolicy Bypass -File setup_startup_shortcut.ps1

To remove: delete "fpl-agent startup.lnk" from shell:startup, or run
remove_startup_shortcut.ps1.
#>
$VbsPath = Join-Path $PSScriptRoot "startup_trigger_hidden.vbs"
if (-not (Test-Path $VbsPath)) {
    Write-Error "startup_trigger_hidden.vbs not found at $VbsPath - it should ship alongside this script."
    exit 1
}

$StartupFolder = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupFolder "fpl-agent startup.lnk"

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "wscript.exe"
$Shortcut.Arguments = "`"$VbsPath`""
$Shortcut.WorkingDirectory = $PSScriptRoot
$Shortcut.Description = "fpl-agent: starts FPLAgentSync/FPLAgentLivePoll/FPLAgentLiveServer at login"
$Shortcut.Save()

Write-Host "Created startup shortcut: $ShortcutPath"
Write-Host "This runs automatically at every Windows login (no admin rights needed) and starts"
Write-Host "any of FPLAgentSync/FPLAgentLivePoll/FPLAgentLiveServer that isn't already running."
Write-Host "Remove by deleting: $ShortcutPath"
