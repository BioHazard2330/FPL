' Opens the dashboard on demand (2026-10-13, power gating).
'
' Outside the pre-deadline window the dashboard server is not left running, so
' it is not eating CPU and RAM while the machine is used for something else.
' This starts it (a second start is harmless: the server's own single-instance
' lock makes it exit at once), waits for it to answer, then opens the browser.
' Outside the window the server stops itself ~30 minutes after the last tab is
' closed; inside the window it is already running and this just opens the page.
'
' Usage: double-click the "FPL Dashboard" desktop shortcut
' (scripts\setup_dashboard_shortcut.ps1 creates it).
Option Explicit
Dim fso, sh, root, exePath, url, i
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
exePath = fso.BuildPath(root, ".venv\Scripts\fpl.exe")
url = "http://127.0.0.1:8877/"
sh.CurrentDirectory = root

If Not IsUp(url) Then
    sh.Run """" & exePath & """ live-server --port 8877", 0, False
    For i = 1 To 90
        If IsUp(url) Then Exit For
        WScript.Sleep 1000
    Next
End If
sh.Run url

Function IsUp(target)
    Dim http
    IsUp = False
    On Error Resume Next
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    http.setTimeouts 1000, 1000, 1000, 1000
    http.open "GET", target, False
    http.send
    If Err.Number = 0 Then
        If http.status = 200 Then IsUp = True
    End If
    On Error GoTo 0
End Function
