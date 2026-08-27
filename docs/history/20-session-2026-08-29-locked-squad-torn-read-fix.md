# Session 20 — 2026-08-29: locked-squad "randomly no squad" bug, root-caused and fixed

Direct user report, mid-session: "the dashboard says no squad and dies. and refreshing doesn't
work." Investigated and fixed the real root cause rather than guessing at a workaround.

## Investigation

`data/dashboard.html` on disk genuinely showed "No real locked squad" - not a browser caching
artifact. `fpl my-team` and a direct `get_locked_squad(conn)` call both returned the real squad
fine in isolation; 3 back-to-back isolated `fpl dashboard` regens also came back clean, ruling out
a deterministic bug in this session's own earlier P0/P1 changes. `logs/fpl_agent.log` showed the
Windows Task Scheduler's own `run-scheduled` job (real, independent of any interactive Claude
session, per this project's own automation architecture) firing every ~15-30 minutes throughout -
confirming a real concurrent writer was active against the same `data/fpl.db` the whole time. No
`sqlite3.OperationalError`/"database is locked" ever appeared in the log, ruling out simple lock
contention as the visible mechanism.

Traced to `ingestion/my_team.py::get_latest_squad`: two separate, un-transacted `SELECT`s -
`MAX(event)` to find the latest synced event, then a second `SELECT ... WHERE event=?` for that
event's picks. `ingestion/my_team.py::_upsert_picks` does a real `DELETE FROM my_team_picks WHERE
entry_id=? AND event=?` immediately followed by re-`INSERT`s for that same event whenever a resync
happens for the already-latest event. Python's `sqlite3` module does not auto-wrap a sequence of
plain `SELECT`s in one transaction/snapshot - if the writer's delete-then-reinsert lands between
the two reads, the second `SELECT` genuinely sees zero rows for an event the first `SELECT` just
proved exists. This is a real torn read, not an exception, which is exactly why the incident left
no trace anywhere in the log - `_xi_from_real_picks`'s own `if not picks: return None` early return
was itself silent (unlike its two sibling malformed-data cases, which already logged warnings from
a prior 2026-08-28 fix for a related "intermittent no-squad" report).

## Fix

1. `get_latest_squad` rewritten as ONE real atomic statement (`event=(SELECT MAX(event) ...)` as a
   scalar subquery, plus the `event` column itself now selected from the same row set) - SQLite
   guarantees a single statement's result reflects one consistent snapshot, closing the race
   structurally rather than papering over one observed symptom.
2. `_xi_from_real_picks`'s previously-silent empty-picks path now logs a real warning naming the
   entry/event, closing the "left no trace" half of the bug for any future, narrower recurrence
   (the remaining residual window: `get_latest_squad`'s result and `_xi_from_real_picks`'s own
   separate re-query for the same already-resolved event, in the rare case a resync targets that
   exact already-current event again).
3. `database/connection.py::get_connection` raised the sqlite connection timeout from Python's 5s
   default to 30s - general defensive hardening against genuine cross-process write contention on
   this same real, actively-scheduled database file, not proof this was the exact mechanism (the
   confirmed root cause is the torn read above).

Because `data/dashboard.html` is a static file regenerated only periodically (the scheduler, or a
manual `fpl dashboard`), one bad read during any single regen baked the broken "no squad" state
into the file for up to ~30 minutes - explaining "refreshing doesn't work" precisely: the browser
was correctly re-fetching the same broken static file every time, since nothing regenerates it
live.

## Tests

3 new tests: `get_latest_squad` proven to issue exactly one query against `my_team_picks`
(`sqlite3.Connection.set_trace_callback`, not monkeypatching `.execute` directly - the C-level
method slot is read-only) and to resolve the MAX event's own picks correctly across multiple
stored events; `_xi_from_real_picks` proven to log the new diagnostic warning on the residual-race
path. Full suite green (see commit for the exact count) - live-verified via a fresh `fpl dashboard`
regen after the fix (0 occurrences of "No real locked squad").
