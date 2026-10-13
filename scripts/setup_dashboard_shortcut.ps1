<#
Creates an "FPL Dashboard" shortcut on the desktop that starts the dashboard
server on demand and opens it (see start_dashboard.vbs). Needed because the
server no longer runs all day: outside the 24h pre-deadline window it is
started when you want it and stops itself after ~30 idle minutes.

Usage: powershell -ExecutionPolicy Bypass -File setup_dashboard_shortcut.ps1
Remove it by deleting the shortcut file.
#>
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Launcher = Join-Path $PSScriptRoot "start_dashboard.vbs"
if (-not (Test-Path $Launcher)) { Write-Error "start_dashboard.vbs not found at $Launcher"; exit 1 }
$Desktop = [Environment]::GetFolderPath("Desktop")
$Link = Join-Path $Desktop "FPL Dashboard.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($Link)
$Shortcut.TargetPath = "wscript.exe"
$Shortcut.Arguments = "`"$Launcher`""
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Description = "Open the fpl-agent dashboard (starts the server if it is not running)"
$Shortcut.Save()
Write-Host "Created $Link"
