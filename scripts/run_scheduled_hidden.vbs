' Runs an executable with zero visible window - Task Scheduler launching a
' console .exe directly always pops a visible cmd window (fpl.exe is a
' console-subsystem executable, by design of how pip generates entry-point
' scripts), which was a real, reported annoyance: a command prompt flashing
' open every 60 minutes showing raw output nobody asked to see.
' WshShell.Run's third argument (window style 0 = hidden) is the standard,
' reliable way to suppress that on Windows - more bulletproof than
' PowerShell's own -WindowStyle Hidden, which can still flash a window
' briefly on some Windows builds.
'
' Usage: wscript.exe run_scheduled_hidden.vbs "<exe path>" "<args>"
' setup_scheduler.ps1 registers the scheduled task to invoke this with the
' real fpl.exe path and "run-scheduled" as arguments - nothing here is
' meant to be edited by hand.
Set WshShell = CreateObject("WScript.Shell")
ExePath = WScript.Arguments(0)
ExeArgs = WScript.Arguments(1)
WshShell.Run """" & ExePath & """ " & ExeArgs, 0, True
