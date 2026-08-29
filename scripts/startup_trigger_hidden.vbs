' Runs startup_trigger.ps1 with zero visible window at login. This file
' itself stays in the real project's scripts/ folder - a WINDOWS SHORTCUT
' (.lnk, not a copy of this file) lives in the user's own Startup folder
' (shell:startup) and points back at this fixed real path, which Windows
' runs automatically at every logon with no admin rights needed. Uses
' `WScript.ScriptFullName`'s own real directory rather than a hardcoded
' path so this keeps working if the project is ever moved - deliberately
' NOT copied anywhere else (a copy would resolve this same lookup against
' the WRONG folder). See startup_trigger.ps1's own docstring for the full
' real reasoning (closes the "everything must restart automatically after
' a shutdown" gap without requiring an elevated PowerShell session).
Set WshShell = CreateObject("WScript.Shell")
ScriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
TargetScript = ScriptDir & "\startup_trigger.ps1"
WshShell.Run "powershell.exe -ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File """ & TargetScript & """", 0, False
