<#
Removes the "fpl-agent startup.lnk" shortcut from the current user's own
Startup folder (undoes setup_startup_shortcut.ps1). Does not touch the
underlying scheduled tasks themselves - use remove_scheduler.ps1/
remove_live_poll_scheduler.ps1/remove_live_server_scheduler.ps1 for those.
#>
$StartupFolder = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupFolder "fpl-agent startup.lnk"

if (Test-Path $ShortcutPath) {
    Remove-Item $ShortcutPath -Force
    Write-Host "Removed startup shortcut: $ShortcutPath"
} else {
    Write-Host "No startup shortcut found at $ShortcutPath - nothing to remove."
}
