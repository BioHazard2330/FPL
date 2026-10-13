' Starts an executable hidden - but only when the power gate allows it.
'
' Usage: wscript.exe gated_launch.vbs <mode> "<exe path>" "<args>"
'   mode "sync"   : run when the active window is open OR today's daily run is
'                   still owed (the first launch of each day gathers everything
'                   and exits).
'   mode "window" : run only while the active window is open (live poll and
'                   dashboard server).
'
' The window is the last 24h before the next FPL deadline (config/power.yaml);
' src/fpl_agent/scheduler/power_window.py writes it to data\power_gate.txt after
' every cycle. This script reads that file and nothing else, so a launch that
' decides "not now" costs a few milliseconds and never starts Python - the point
' of the whole exercise (no resident or repeatedly-spawned Python processes
' while the machine is being used for something else).
'
' Fails OPEN: no gate file, an unreadable one, or a window that has already
' passed all mean "run", because that run is what refreshes the gate. A broken
' gate can cost CPU; it can never silence the sync.
Option Explicit
Dim fso, sh, mode, exePath, exeArgs, gatePath, gate, allow, active, dailyDue
Dim nowUtc, startT, untilT, offset, today, stream, line, p

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
mode = LCase(WScript.Arguments(0))
exePath = WScript.Arguments(1)
exeArgs = WScript.Arguments(2)
gatePath = fso.BuildPath(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)), "data\power_gate.txt")

allow = True
active = True
dailyDue = False
Set gate = CreateObject("Scripting.Dictionary")

If fso.FileExists(gatePath) Then
    On Error Resume Next
    Set stream = fso.OpenTextFile(gatePath, 1)
    Do While Not stream.AtEndOfStream
        line = stream.ReadLine()
        p = InStr(line, "=")
        If p > 1 Then gate(Trim(Left(line, p - 1))) = Trim(Mid(line, p + 1))
    Loop
    stream.Close
    On Error GoTo 0

    If gate.Exists("from") And gate.Exists("until") And gate.Exists("utc_offset") Then
        startT = CLng(gate("from"))
        untilT = CLng(gate("until"))
        offset = CLng(gate("utc_offset"))
        nowUtc = DateDiff("s", DateSerial(1970, 1, 1), Now()) - offset
        If untilT > 0 And nowUtc <= untilT Then
            active = (nowUtc >= startT)
        Else
            active = True   ' no window recorded, or it has passed: let the app refresh the gate
        End If
    End If

    today = Year(Date) & Right("0" & Month(Date), 2) & Right("0" & Day(Date), 2)
    If gate.Exists("daily_done") Then
        dailyDue = (gate("daily_done") <> today)
    Else
        dailyDue = True
    End If
End If

If mode = "window" Then
    allow = active
ElseIf mode = "sync" Then
    allow = (active Or dailyDue)
End If

If allow Then
    sh.Run """" & exePath & """ " & exeArgs, 0, True
End If
