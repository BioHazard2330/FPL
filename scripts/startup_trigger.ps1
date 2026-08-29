<#
Real reboot-survival closer (2026-08-29, direct user requirement: "even if
i shut down my laptop and the next day i turn it on, everything starts
automatically with no issues"). This project's 3 real scheduled tasks
(FPLAgentSync, FPLAgentLivePoll, FPLAgentLiveServer) all run with
LogonType=Interactive - they can only ever run while the real user is
actually logged into Windows (Task Scheduler cannot start an interactive-
session task before anyone logs in - a genuine, disclosed limit of this
approach, not something a plain trigger or a startup script can bypass
without either storing the user's Windows password or running as a
service, and this project's own standing rule never handles credentials).

A real, confirmed platform gap prevented the cleaner fix: registering an
`AtLogOn` scheduled-task trigger requires Administrator privileges even
for a task you already own (confirmed live - `Register-ScheduledTask`
failed with "Access is denied" specifically and only for that trigger
type, isolated via a throwaway test task, in a session that is NOT running
elevated). Rather than ask for an elevated PowerShell session, this script
+ its Startup-folder shortcut achieve the exact same practical outcome
(everything live again the moment the user logs in) through a path that
needs zero elevation: any file a standard user places in their own
`shell:startup` folder runs automatically at every login, no admin rights
required, ever.

What this script actually does: fires `Start-ScheduledTask` for all 3 real
tasks. Every one of them is ALREADY safe to re-trigger even if it's still
running from before the shutdown/before this script runs (`-MultipleInstances
IgnoreNew` on all 3, backed by this project's own real PID-based singleton
lock, `scheduler/process_lock.py`) - so this is never a duplicate-process
risk, only ever a genuine "start it if it isn't already going" nudge.
#>

$tasks = @("FPLAgentSync", "FPLAgentLivePoll", "FPLAgentLiveServer")
foreach ($name in $tasks) {
    try {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction Stop
        Start-ScheduledTask -TaskName $name -ErrorAction Stop
    } catch {
        # Real, non-fatal: a task that isn't registered yet (first-ever
        # setup not done) or a transient Task Scheduler hiccup must never
        # stop the other 2 real tasks from getting their own real start
        # attempt - this script's whole job is "best-effort nudge at
        # login," not a strict all-or-nothing startup sequence.
        continue
    }
}
