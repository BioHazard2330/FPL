# Session 2026-09-19 — three pending full-time analyses cleared, sync unwedged

Direct user ask: "do everything pending. nothings been synced for the agent
and dashboard." Two tracks — the three queued FULL_TIME qualitative-analysis
jobs (63/65/67), and a sync that had produced nothing since 2026-09-15.

## Why nothing had synced

Not a 4-day gap in the scheduler registration — the machine was simply off
between 2026-09-15 19:56 and 2026-09-19 12:16. The real problem was what
happened when it came back up.

`FPLAgentSync` started at 12:16:24 and was still running 30 minutes later
having logged **not one** scheduler line (its first is normally
`run-scheduled sync ok:` within seconds). It was burning ~22% of a core the
whole time. The decisive measurement was the database itself: `data/fpl.db`,
`-shm` and `-wal` were all untouched since 12:16:33, with the WAL frozen at
8 KB. Thirty minutes of CPU and zero bytes written — an open, uncommitted
write transaction going nowhere.

Meanwhile `live-server`'s materiality engine logged
`sqlite3.OperationalError: database is locked` every ~43 seconds, 150 times,
each one a `PRICE_CHANGED` event failing
`_maybe_trigger_strategic_plan_recompute`.

The mechanism: `run_scheduled` registers the materiality engine on the event
bus **before** calling `run_sync()` (a deliberate 2026-08-29 decision, so the
gate fires the instant a material event lands rather than once per tick).
After four days offline the catch-up sync carried a 73-price-event backlog.
Each one re-entered the recompute gate while `run_sync` still held its own
write transaction — the sync deadlocking against its own emitted events.

Killing the wedged process was safe by design: SQLite rolls back an
uncommitted transaction, and `process_lock.py` reclaims a lock whose PID is
dead. The WAL jumped 8 KB → 222 KB the instant it died as the blocked writers
drained — direct confirmation that process was the sole blocker.

The very next `run-scheduled` refused to start with `another live-poll
instance is already running (pid 12112)` against the PID just killed;
`_pid_is_alive(12112)` returned `False` when tested directly moments later,
so this was transient (PID reuse, or the `tasklist` failure path in
`_pid_is_alive` returning its "assume alive" fallback). A second invocation
ran the full chain cleanly and has not recurred. **Not root-caused — left
open below.**

Clean run: 33 lifecycle + 73 price events, 40 fotmob matches upserted, xg
backfill 1 match/31 player rows, predicted-lineup 1 change,
lineup-probability 2 changes, solio GW6 60/60, cross-competition 20 teams,
news 149 fetched/108 new, my-team `entry=7378572`, live rank ~1,236,343 (from
~1,298,652 on 09-15), 18 alerts delivered, dashboard + live snapshot
regenerated.

## `fpl match-report` crashed on a null-xG shot

Job 67 (Leeds 4-1 Newcastle) could not be read at all:

```
TypeError: unsupported format string passed to NoneType.__format__
  cli/main.py:672  f"... xg={s['xg']:.2f} ..."
```

`match_shots.xg` is nullable and 6 rows across the whole DB are null; the
surrounding code already guards `x`/`y`/`shot_type`/`situation` for exactly
this and `xg` was simply missed. Fixed with the same None-guard style
(`xg=?`). `match_events.team_id` has 160 nulls but renders through a bare
`{}` with no format spec, so it was left alone.

The one null-xG shot in this match turned out to be load-bearing — see below.

## The three analyses

Written per `.claude/skills/match-intelligence-analysis/SKILL.md`, all three
persisted via `fpl match-analyze --phase full_time`. 31 observations, 22
implications, 22 player states, 6 team states, 12 material change events.

**Coventry 0-5 Brighton (5795448).** Groß took and scored the 70' penalty
(0.79 xG, the match's largest chance) and assisted the 35' and 90' goals 55
minutes apart. Brighton's five goals came from scoring shots worth 1.36 xG —
0.57 excluding the penalty. Coventry's shape: 10 of 16 attempts from
throw-in/corner/set-piece phases, no open-play shot above 0.24 xG, Bobby
Thomas taking three headers all from dead balls.

**Man Utd 0-1 Man City (5795452).** Haaland's two shots carried 0.75 of
City's 0.99 xG; the goal came from a 0.44 chance, not a low-probability
finish. Man Utd took 16 shots at 0.06 xG each with only 4 from x≥94 and two
posts.

**Leeds 4-1 Newcastle (5795450) — the 32' goal is an own goal.** Not flagged
anywhere in the schema. Three independent checks agree: the shot is filed to
a Newcastle player at x=14, the opposite end from every other team-17 attempt
(80–103); its xG is null; `player_match_state` credits Miley 0 goals; and
Newcastle's `team_match_state` counts 7 shots / 0.85 xG, matching the 8
`match_shots` rows *minus exactly this one*. So Leeds scored three goals of
their own from 0.36 xG of shots — the 4-1 overstates them substantially.
`match_events.team_id` records the *benefiting* side, not the shooter's, and
is therefore unreliable for goal attribution.

Verified end-to-end rather than at the DB: `/api/football` serves the new
evidence, and the COMMAND screen's FOOTBALL EVIDENCE panel renders the
written strings verbatim ("De Cuyper — 1 assist, 4 key passes… +0.08 xP
applied to assists", "Haaland — 1 goal, 2 shots, 0.75 xG — +1.03 xP applied
to goals"), with captain robustness now reading `Haaland:
qualitative_analysis (None -> POSITIVE)`. The analyses reached the decision
layer, not just storage.

## Data-quality findings recorded in the payloads' `uncertainties`

- Coventry's `team_match_state` (14 shots / 1.39 xG) does not reconcile with
  `match_shots` (16 rows / 2.03 xG). Brighton's and Man Utd's reconcile
  exactly, so this is per-match, not systemic.
- `player_match_state` for Sidiki Cherif records `shots=0, xg=0.0` while
  `match_shots` holds his 63' header at 0.40 — the largest Coventry chance is
  absent from his own aggregate row.
- `player_match_state.minutes` is NULL for every player in 5795452 and
  5795450; only 5795448 has it.
- `player_id=459` maps to two different `fotmob_player_id`s in 5795450
  (1296763 starting, 1867092 benched) — a name-matching collision; any row
  keyed on 459 may conflate two players.
- Duplicate substitution rows in `match_events` (72'/73' in 5795450, 77'/78'
  in 5795448).

## the-odds-api: out of credits, not broken

`run-scheduled live-odds sync failed` is HTTP 401. Confirmed the precise
cause rather than assuming: `OUT_OF_USAGE_CREDITS`, with
`x-requests-used: 500`, `x-requests-remaining: 0`. The key is valid; the
monthly 500-credit budget is spent — consistent with the pre-throttle burn
documented 2026-09-13. The 6h `should_sync` gate is in place and the step is
non-fatal, so this resolves itself on the next billing cycle. No code change.

## Second pass — the screens were still stale, and why

User follow-up: "everything is not synced yet. team matchweek command
whatever, they arent upto date." Correct, and for a reason the first pass
had not looked at.

### Every `/api/*` payload was built with no live data at all

`build_dashboard_context(conn, live_payload=...)` takes the FPL live-event
payload as a parameter. `assemble.py` (the old Python-rendered
`dashboard.html`) passes it. **Both API-layer callers did not** —
`get_cached_dashboard_context` and `run_context_refresh_loop` each called
`build_dashboard_context(conn)` bare, so `live_payload` was always `None`
for the React app, which is the real default UI.

Downstream of that single omission, `_compute_my_live_score` returns `None`
on its first line, and so:

- COMMAND `bar.actual_points` was `null` during a live gameweek
- MY TEAM `actual_points_label` was `""`
- `xp_summary_label` read `"projected xP"` instead of `"next-GW xP"`

A regression dating from the 2026-09-08 Phase 8.2 Stage 2 API extraction:
the old dashboard kept working, so nothing looked broken from the CLI side.

Fixed by moving `_maybe_fetch_live_payload` out of `cli/main.py` into
`monitoring/dashboard/context.py` as `maybe_fetch_live_payload` (both real
context paths need it, not just the CLI) and passing it in both API callers.
`cli/main.py` imports it rather than keeping a second copy. No new network
cadence: the helper is self-gating and returns `None` with zero traffic
unless a fixture for the live/reference event has `started=1`, and the
context refreshes on its existing 480s / 45s-when-live interval.

Verified live against GW5 in progress: helper returned 662 elements with 29
scoring; `actual_points` went `null` → `4.0`, `actual_points_label` `""` →
`"4 GW5 pts"`, `xp_summary_label` → `"next-GW xP"`.

### The decision itself was three days old

Separately, COMMAND served `computed_at: 2026-09-15T20:23`, `is_stale: true`,
`recompute_status: RECOMPUTING`, `decision_id: 3133`. The recompute
auto-triggered at 12:58 was genuinely working, not wedged — 97% of a core,
unlike the earlier sync at 22% doing nothing — and completed at 13:07:57,
writing decision 3136. After the live-server restart COMMAND reports
`is_stale: false`, `age_relative: 15m ago`, `recompute_status: CURRENT`, and
the UI replaced the stale "WILDCARD SQUAD 3-5-2" with the current
"FODEN -> MBEUMO SQUAD 4-5-1".

**The live-server had to be restarted for the code fix to apply** — it holds
its imports in memory for the life of the process, the same trap recorded in
session 34. Editing the file changes nothing until the process is recycled.

### The deadlock, fixed

`live/materiality_engine.py` gained a re-entrant `suspended()` context
manager; `run_scheduled` wraps `run_sync()` in it. Routed events arriving
while suspended set a pending flag instead of running the gate, and the gate
runs exactly once on exit if anything arrived. This does not change what
counts as material — the gate is a *global* question ("has anything material
happened since the last plan?"), so 73 sequential identical checks were
redundant work even setting the deadlock aside. Reactivity is unchanged in
`live_match_poll_cmd`/`refresh_in_progress_matches`, which hold no long write
transaction and never suspend. Verified directly: 73 events while suspended
produce 0 checks during and exactly 1 coalesced check after; an empty suspend
produces none; unsuspended behaviour is per-event as before; nested suspends
do not resume early; and an exception inside the block still drains and
restores depth.

### The key leak was one level up from where it looked

`odds_live_source.fetch_live_odds_payload` already redacts deliberately — it
builds its message only from known-safe fields and documents never
interpolating `str(exc)`. The leak was `cli/main.py`'s
`logger.exception(...)` in the odds `except`, which writes the full chained
traceback; the `OddsLiveFetchError` is raised `from exc`, so the original
`requests.HTTPError` — whose `__str__` carries the URL including
`apiKey=<live key>` — landed in the log anyway. Now `logger.error(..., e)`,
no traceback. The already-exhausted key should still be rotated, since it
sits in the existing log file.

367 tests green across the materiality/run-scheduled/dashboard/context/api/
live-snapshot/events suites.

## Open, not fixed this session

- **The spurious stale-lock refusal** against a dead PID. `_pid_is_alive`'s
  `OSError`/timeout path deliberately returns `True` ("never steal a lock we
  can't verify is free"), which is the right default but makes a transient
  `tasklist` failure look exactly like a live holder. Worth distinguishing.
- **`ODDS_API_KEY` already sits in `logs/fpl_agent.log`** from before the
  redaction fix. `logs/` is gitignored so nothing reached the remote, but the
  key is on disk in cleartext and is worth rotating.
- **`get_cached_dashboard_context` still cannot invalidate early** on a
  material change (its own pre-existing disclosed follow-up). With live
  fixtures the 45s refresh makes this mostly moot; outside one, a fresh
  decision can wait up to the 600s TTL to appear.
