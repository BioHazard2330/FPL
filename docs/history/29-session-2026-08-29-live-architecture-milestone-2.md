# Session 2026-08-29: live architecture rebuild, milestone 2 (real-time SSE transport)

Continuation of the "live architecture rebuild" spec (milestone 1 built
the event bus + fast engine). User said "continue" after milestone 1's
report offered three next-milestone candidates in dependency order (SSE
transport, materiality-gate wiring, FPL-provider abstraction) - proceeded
with the first, SSE transport, as planned.

## Real cross-process constraint

Milestone 1's `EventBus` is a real, correct, in-process singleton - but
`live-match-poll` (ingestion) and any client-transport server are
necessarily SEPARATE real OS processes (each `fpl` CLI invocation is its
own process). An in-process bus cannot span them without real new
infrastructure (a socket, a message broker) this project's own
free-resources/single-laptop constraints don't call for.

**Real solution**: `live/sse_server.py::DbTailer` polls the SAME real,
already-persisted append-only tables (`match_events`, `change_events`)
plus `live_snapshot.json`'s own mtime, on a ~1.5s cycle, translating each
genuinely new row/version into a real SSE broadcast. This is simultaneously
the transport AND the reconciliation mechanism the spec's own section 9
asks for - every push is read straight from the authoritative persisted
state, never from an in-memory-only fact that could drift from it.

## New: `fpl live-server` (`live/sse_server.py`)

A real, stdlib-only `ThreadingHTTPServer` (no new dependency) exposing:
- `GET /events` - a real Server-Sent-Events stream. Each connected browser
  tab gets its own `queue.Queue`; `Broadcaster.broadcast()` fans a message
  out to every registered queue. A 15s keep-alive comment (`: keep-alive`)
  keeps idle connections from being silently dropped by intermediate
  proxies/browsers.
- Static file serving for anything else under `data/` (so this server can
  fully replace a manual `python -m http.server` for real, real-time use -
  same origin as `/events`, no CORS complexity needed for the common case).

Deliberately a SEPARATE process from `live-match-poll` (per the spec's
own explicit "if the platform can't support a persistent worker, separate
it from the dashboard/API" allowance) - own CLI command, own single-
instance lock (`data/live_server.lock`, reusing `scheduler/process_lock.py`,
the same real stale-PID-recovery mechanism `FPLAgentLivePoll` already
uses).

## Real bug found + fixed: a genuine startup race

First version computed the tailer's baseline `MAX(id)` lazily, inside the
background thread's own init - found live by this milestone's own test
(`test_sse_stream_delivers_a_real_new_match_event`, which passed with a
raw socket but returned an empty message list until this was fixed): a
row inserted in the real window between `LiveServer(...)` returning and
the tailer thread actually getting scheduled would be wrongly treated as
"already existed at startup" and silently never broadcast - a real,
production-relevant race (a goal scored in the first second after
`live-server` starts could have been missed). Fixed by capturing both
baselines (`match_events`/`change_events` MAX ids) synchronously in
`LiveServer.__init__`, on the constructing thread, before `.start()` ever
returns - closes the race for real, not just for the test. A dedicated
regression test (`test_baseline_ids_captured_synchronously...`) locks
this in: a row inserted BEFORE `.start()` is even called must still be
reported as real/new.

## Real bug found + fixed: `requests`/urllib3 streaming quirk (test-only)

While writing the streaming tests, `requests.get(..., stream=True)`
against this server's real HTTP/1.0, no-`Content-Length` SSE response
never returned data, even though a raw `socket` client (and a real
browser's native `EventSource`, which speaks HTTP/1.1 and handles this
response shape as designed) received every real byte within one tailer
cycle - confirmed directly with a standalone script before concluding
this was a `requests`-specific limitation, not a server bug. Streaming
SSE tests use a plain `socket` instead; static-file tests keep `requests`
(a plain request/response, unaffected).

## Browser wiring (`assemble.py`)

A new, minimal `EventSource('http://127.0.0.1:8877/events')` connection,
added inside the SAME script scope as the existing `applySnapshot`
function so it can call it directly - zero duplicated logic. Only the
`snapshot` channel is wired this pass: a real `live_snapshot.json` write
now reaches the browser within about one tailer cycle (~1.5s) instead of
waiting up to the existing 10s poll interval, and `applySnapshot`'s own
version guard makes an out-of-order or duplicate push a safe no-op for
free. `match_event`/`change_event` channel messages are received and
broadcast by the server but NOT yet rendered in the browser - a real,
disclosed follow-up (they'd need their own dedup-key scheme reconciled
with `pushLiveChanges`'s existing one, to avoid a double-counted feed
entry when both the SSE push and the next poll cycle describe the same
real incident). The existing ~10s snapshot poll is completely unchanged
and untouched by this pass - it is now genuinely the fallback/
reconciliation path, not removed or degraded.

## Scheduler scripts (prepared, not run)

`scripts/setup_live_server_scheduler.ps1`/`remove_live_server_scheduler.ps1`,
mirroring the existing `setup_live_poll_scheduler.ps1` pattern exactly
(periodic relaunch trigger, `MultipleInstances IgnoreNew`, the real
process lock makes a relaunch attempt against an already-running server a
safe no-op). Not registered this session - modifying the Windows Task
Scheduler is a persistent, hard-to-reverse system change or user's own
call, not something to do without being asked, matching how the existing
scheduler scripts were themselves clearly built for the user to run
manually.

## Verification

7 new tests (`test_sse_server.py`) - all against a REAL started
`ThreadingHTTPServer` on a real ephemeral port, driven with real HTTP/
socket requests, never a mocked transport layer: static file serving,
403 on path traversal, 404 on a missing file, a real new `match_events`
row reaching the stream, a real `live_snapshot.json` write reaching the
stream, the startup-race regression, and broadcaster client-count
tracking. Also smoke-tested directly against the REAL production `data/`
directory (a genuine `fpl live-server` process, `dashboard.html` and
`live_snapshot.json` both served with real 200s, cleanly stopped
afterward - no lingering process, stale lock file cleaned up). 1274 tests
pass (full suite).

## Genuinely not done this milestone (real, disclosed)

The materiality-engine consolidation onto the bus and decision hysteresis
(still milestone 3+ candidates). FPL-side provider abstraction (still
unbuilt). `match_event`/`change_event` channel rendering in the browser
(received server-side, not yet displayed). The Task Scheduler entry for
`live-server` is prepared but not registered. Real production
verification against a genuinely live match with the full SSE path active
end-to-end (no GW was live this session).
