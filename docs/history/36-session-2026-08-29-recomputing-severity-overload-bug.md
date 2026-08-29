# Session 2026-08-29: RECOMPUTING banner - a real severity-field overload bug

Direct follow-up: "why does the fucking dashboard again say recomputing?"

## Root cause

`models/decision_freshness.py::has_material_change_since` looks for the
most recent HIGH-severity `change_events` row since the cached
`strategic_plan` decision was computed, to decide whether the dashboard's
recommendation is stale. The real row that tripped it: a `kickoff_reminder`
event for fixture 15, severity HIGH.

That HIGH label is deliberate and correct - but for a different consumer.
`ingestion/change_detection.py::detect_upcoming_kickoffs`'s own docstring
says so explicitly: "always HIGH severity, matching this project's own
precedent that a genuinely time-critical, narrowly-scoped event... doesn't
need severity nuance" - calibrated for the alerts/notifications panel
("your squad's match starts soon"), which should absolutely surface this
loudly. But `has_material_change_since` reused the SAME `severity` column
for a completely different question - "should the strategic plan be
considered stale" - and a kickoff happening carries zero new information
about any player's form, injury, price, or lineup. The kickoff time was
already known when the plan was computed; a reminder firing later doesn't
change what the plan should recommend. One column, two real consumers with
different real semantics, never reconciled until this report.

## Fix

Excluded `event_type = 'kickoff_reminder'` explicitly from
`has_material_change_since`'s query, rather than lowering its real,
correct severity for the alerts panel it was actually designed for. This
single function is shared by both the dashboard's own freshness check
(`assess_recommendation_freshness`) and `cli/main.py::_maybe_trigger_
strategic_plan_recompute` (the auto-recompute trigger) - one fix closes
both paths, confirmed by reading the call graph rather than assumed.

Verified directly against the real production DB: `is_stale` flipped
`True -> False` for the exact real decision/change-event pair that
triggered the report.

## A real leftover from before the fix - not a second bug

After the fix landed, the dashboard STILL showed RECOMPUTING for a few more
minutes. Investigated rather than assumed broken: the OLD, buggy code had
already fired a real background `fpl strategic-plan` subprocess at
15:11:18 UTC (the auto-recompute trigger reuses the same now-fixed
function) before the fix was written - confirmed live via `Get-CimInstance`
showing a genuine, actively-computing `fpl.exe strategic-plan` process
(914s of real CPU time under this session's own heavy concurrent load).
The dashboard's `RECOMPUTING` status has its own real 15-minute self-heal
window (`monitoring/live_snapshot.py::_RECOMPUTE_LOCK_STALE_MINUTES`) for
exactly this case - a lock older than that is treated as abandoned, never
a permanent stuck state. Waited for the real lock to age past 15 minutes
(a real, live-observed clock check, not assumed), regenerated the
dashboard, and confirmed `data-decision-status="CURRENT"` - a real
screenshot shows "Current · computed 5h ago" with no banner.

## Tests

3 new tests in `test_decision_freshness.py`: the kickoff_reminder
exclusion itself, and a guard that a REAL material HIGH event landing
alongside a kickoff_reminder is still correctly found (the exclusion must
stay narrow, never accidentally swallow a genuine change). 115 tests green
across the broader dashboard/freshness/scheduled-run sweep; live-server
and live-match-poll restarted to pick up the fix (the same "stale
long-running process" class this session already fixed twice before -
confirmed both were started before this fix's mtime).
