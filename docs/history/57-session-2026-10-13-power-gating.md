# Session 2026-10-13 (later) — power gating: nothing resident outside the deadline window

User, verbatim: *"i want the daemon process to only run say 24 hrs before the
deadline . because the python processes that constantly run 24/7 do eat a lot
of cpu and ram and when im gaming and stuff i dont want it to be affected. or
maybe a better way is to do like , say once a day say early morning when my
laptop turns on it runs , gathers all the data does what it has to do then
automatically stops and the cycle continues. and then 24 hrs before the
deadline it runs constantly cos team news or anything could come which is
important"*

Both halves implemented: one gather a day, continuous in the last 24 hours.

## What was actually costing CPU

Not the sync (a short run every 15 minutes). Three things:

1. **The dashboard server's four refresh threads** (`live/sse_server.py`):
   each rebuilds a cache every ~8 minutes, the main one a 60-130 second
   `DashboardContext` build, for the life of the process, whether or not a
   browser was open. Roughly a core's worth of duty cycle, permanently.
2. **The ~20 minute `strategic-plan` job** the sync spawns detached whenever
   a material change lands. It had run for over an hour of wall-clock this
   afternoon with the machine otherwise idle.
3. **A stuck "live" cadence.** `fixtures.finished` stays 0 for days after the
   whistle (FPL awaits bonus confirmation), so `recommended_cadence` and
   `current_live_event` read every played GW6 fixture as in progress and held
   the system in its tightest, most frequent cycle for days. Fixed by also
   requiring "not FULL_TIME" and a kickoff within 5 hours; the cadence now
   reads "deadline in 98h - normal".

## The design

- **Active window** = `deadline - 24h` to `deadline + 3h` (`config/power.yaml`,
  `scheduler/power_window.py::compute_window`). Today's: opens Fri 16 Oct
  15:30 IST (deadline Sat 17 Oct 15:30 IST), 74 hours away.
- **Outside it:** the first launch of each day runs a full gather and exits;
  every other launch is a no-op. The dashboard server and live poll do not
  run. Live-match tracking outside the window is off by default
  (`live_matchday_polling: false`); finished matches are caught up by the
  next daily run (the catch-up added earlier today covers 14 days).
- **Inside it:** sync on its adaptive cadence (30 min, then 15 within 2
  hours of the deadline), live poll, and dashboard server run continuously.
- **The gate is a text file read by VBScript, not Python.** Task Scheduler
  cannot conditionally fire a trigger, and starting Python every 15 minutes to
  decide to do nothing costs more than it saves. `scripts/gated_launch.vbs`
  reads `data/power_gate.txt` (written after every cycle: window start/end, UTC
  offset, the date of the last daily run) and starts the exe only when allowed.
  A launch that says no costs milliseconds and never loads Python. It fails
  **open** on a missing file, an unreadable one, or a window that has already
  passed, because that run is what refreshes the gate.
- **`run-scheduled --gated`** repeats the decision in Python (so a stale gate
  costs one wasted launch, never a wrong run), throttles in-window cycles to
  the cadence, and defers the daily run while a game is running.
- **Dashboard on demand.** Desktop shortcut **FPL Dashboard**
  (`scripts/start_dashboard.vbs`): starts the server, waits for it, opens the
  browser. Outside the window the server stops its background refreshes 20
  minutes after the last request or open tab, and exits after 30 idle minutes.
  The first load after a cold start pays the ~60-130 second context build
  (the page shows loading skeletons while it runs); inside the window the
  server is already warm.
- **Priority.** Every `fpl` process runs below-normal (children inherit it on
  Windows) and the detached strategic-plan job at idle priority, so what
  remains yields to a game even when it does run. `FPL_NORMAL_PRIORITY=1`
  opts out.

## Gaming guard — one thing that did not work first time

First cut treated Windows' `SHQueryUserNotificationState` states 2/3/4
(busy / Direct3D fullscreen / presentation) as "a game is running". Live, the
state was already 2 while no game was running — the desktop app in
fullscreen — and the first daily run was deferred for it. State 2 is what
Windows reports for *any* fullscreen window, including a browser in F11. Now
3 and 4 always count; 2 counts only while CPU is at or above 50% over a
second. A deferral is also bounded: after 36 hours without a good run it runs
regardless.

## Verified

- 14 unit tests in `tests/test_power_window.py`: the window (opens 24h out,
  stays open through the grace then moves to the next deadline, none on
  record, gating disabled), the gate file round trip and its "cannot say"
  cases, the gated decisions (in-window cadence throttle, once a day,
  fullscreen deferral and its 36h override), the stuck-live fixture, and the
  dashboard server's idle behaviour (refreshes stop outside the window when
  nobody is there, an open tab keeps them, exit only outside the window, never
  when the gate cannot say). `test_scheduler_adaptive.py` runs the legacy path
  with gating off and gains one test that gating leaves the registered
  interval alone.
- The VBS gate, with a harmless `cmd.exe` as the target and the gate file
  edited by hand: daily owed + window closed -> `sync` runs, `window` does
  not; window open -> both run; no gate file -> both run; gate restored ->
  neither runs.
- Tasks re-registered (`FPLAgentSync` 15 min `sync`, `FPLAgentLivePoll` 3 min
  `window`, `FPLAgentLiveServer` 5 min `window`); first gated daily run
  completed and wrote the gate; a server started by hand serves `/api/table`
  in 0.6 s at BelowNormal priority and was stopped afterwards.

## Open

- A deliberately **Windows-only** guard; on another OS the fullscreen check
  says no.
- If the laptop is off through the whole 24-hour window there is no
  continuous run; the next launch after boot does the daily gather and the
  window arithmetic carries on from there.
- **Not changed, found on the way:** the freshly computed plan (decision 5873)
  recommends `Davis -> Mendy [REVIEW, FRAGILE]` at +3.96 over rolling, below
  the 7.5 noise bar for an 8-gameweek horizon, while the strongest candidate
  (Gibbs-White -> Cherki, +8.33) clears it. The haircut walk in
  `build_authoritative_decision` skips down the near-tied top of the ranking
  (486.05 / 485.70 / 485.69 - gaps of 0.35 and 0.01, none of which "survive
  the haircut") to the first candidate whose gap to the next one does, which is
  a much weaker transfer. The ROLL rule from 2026-09-19 judges the strongest
  candidate, not the chosen one, so neither catches it. Needs a decision about
  what the right behaviour is for a near-tied top group before changing it.
