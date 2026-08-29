# Project State

Last updated: 2026-08-29 (ApexCharts visualization-system rebuild). Read this before
resuming work — it's the current, load-bearing snapshot, kept lean on purpose. **Don't add
session narrative here** — a new capability/architecture change gets one short factual entry;
the story of how it was built, bugs found, and live-verification detail goes in `docs/history/`
(one new dated file per session, indexed in `docs/history/README.md`).

## Where things stand (updated 2026-08-29, ApexCharts visualization-system rebuild)

Every quantitative chart on the dashboard now uses the real ApexCharts type
matched to its data semantics, not one generic area-chart config
everywhere: live rank/points get a real `datetime` axis with real squad
goal/card event annotations and a stepline for points (discrete scoring
events, not a continuous drift); captain contribution and actual-vs-
expected are real column/grouped-column charts; match momentum
(`monitoring/dashboard/match_centre.py::_momentum_chart_html`) is a real
diverging area, replacing hand-rolled SVG. Four genuinely new charts:
projection floor/median/ceiling range (per squad player, real `PlayerCandidate`
data, zero new queries), Dixon-Coles team-strength bar, xG-vs-xA scatter,
and per-match player-form line — all real, already-computed or already-
stored data. Persistent chart instances (`window.dashboardCharts`) with
real incremental `appendData` live updates replace the old destroy-recreate-
every-poll pattern. Full account, including 6 real bugs found and fixed
live (a config-nesting bug that broke every chart identically, a
`market_teams`/`teams` id-space mismatch, an unsupported JS-function
`fill.opacity`, a stale-process SSE bug, axis-precision collapse, and new
permanent per-chart error isolation): `docs/history/35-session-2026-08-29-
apexcharts-visualization-rebuild.md`.

**Follow-up pass, same day**: a more detailed 14-chart spec added 3 more
real charts (captain impact - a live intragame stacked column, dynamically
bucketed to stay readable across a GW spanning several real days; player
value, real xP-per-£m; a real fixture-difficulty heatmap, additive
alongside the existing grid — not a replacement, reconciling the earlier
"keep the grid" call with this pass's explicit re-ask). Two real functional
bugs fixed: `live-match-poll` never regenerated the dashboard for a match's
own FIRST transition into LIVE (the direct cause of a real "game's online
but not on the dashboard" report — fixed, `cli/main.py::live_match_poll_cmd`
now triggers a real regen on that transition specifically, not just on
FULL_TIME); `get_locked_squad()`'s retry now sleeps briefly between attempts
(the previous zero-delay 2-retry version could still occasionally lose the
race under this project's own real heavy concurrent load). Full responsive
QA at 1440/1024/768/390px, real screenshots, zero console errors.

**Reboot survival**: `scripts/setup_startup_shortcut.ps1` places a real
Windows Startup-folder shortcut (no admin rights needed) that starts all 3
real scheduled tasks at every login — closes "must run automatically even
after a shutdown" without needing Administrator privileges (confirmed live
that the cleaner `AtLogOn` scheduled-task trigger requires them, even for a
task you already own). Real, disclosed limit: this starts everything the
moment the user logs into Windows, not before anyone has logged in at all -
closing that fully would need a Windows Service or stored credentials,
both out of scope for a personal-laptop tool with this project's own
standing "never handle credentials" rule.

## Where things stand (updated 2026-08-29, autonomy correction pass)

Real root cause found for a fresh "no squad / live tracking stuck / graphs
look bad" report right after the previous pass's fixes: `fpl live-server`
had never actually been registered in Task Scheduler (the setup script
existed, was never run) and the running `fpl live-match-poll` instance
predated every fix made earlier the same day - both persistent processes
were serving stale, pre-fix in-memory code regardless of what had landed on
disk. Fixed: registered `FPLAgentLiveServer` for real (port 8877, matches
docs), killed both stale processes so fresh ones pick up current code.
Corrected a real logic bug in the previous session's draft `locked_squad.py`
retry (it retried a pure function with identical input - a no-op); now
re-fetches fresh on each of up to 2 attempts and catches `sqlite3.
OperationalError`. Live chart marker labels rewritten (real rounded
background pill + collision-avoidance nudge, replacing bare `fillText` that
could overlap the x-axis with only 2 real GW data points); area fills
changed from flat single-alpha to a real top-to-bottom gradient fade. Full
account: `docs/history/34-session-2026-08-29-autonomy-correction-pass.md`.

**Standing operational note**: this project has two persistent, unattended
processes (`live-server`, `live-match-poll`) that only pick up a code fix
when they themselves restart - both now have Task Scheduler auto-relaunch-
on-exit, but a process that's merely alive-but-stale (not crashed) still
needs an explicit kill to pick up a fix immediately. Check `Get-
ScheduledTask -TaskName FPLAgentLiveServer,FPLAgentLivePoll,FPLAgentSync`
and process start times vs source `mtime` if something looks stale again.

## Where things stand (updated 2026-08-29, visual-quality correction pass)

Direct, harsh follow-up correction after the forensic redesign pass below.
Real crest fix (not a substitute): the official PL badge CDN only 403s a
BROWSER's cross-origin `<img>` (checks `Referer`) - a server-side fetch
succeeds. `fpl sync-crests` (`ingestion/crest_assets.py`) fetches each
real team's crest once and caches it to `data/crests/`; dashboard
rendering (`legacy.py::_crest_html`) only ever does a fast, network-free
cache read - wired into every crest call site dashboard-wide (Team
Outlook, Match Centre, Fixture Ticker, Market, Opportunity Board, Expected
Data, Points Changes, Price History, Injuries, and Live Tracking rows,
which previously showed no team identity at all). Team Outlook's Attack/
Defence columns removed (FPL's own strength data is genuinely unpublished
this early - a dash on every row read as broken, not honest). Rank/
points/captain/actual-vs-expected charts rewritten from hand-rolled SVG to
real Chart.js 4.4.9 (vendored locally to `data/vendor/`, MIT license, no
live CDN dependency). Full account: `docs/history/33-session-2026-08-29-
visual-quality-correction.md`.

**Genuinely still open**: `fpl sync-crests` is manual, not scheduled -
re-run it if a club rebrands mid-season. Momentum/shot-map charts stay
SVG (a pitch-relative scatter doesn't fit a generic line-chart library).
A pre-existing `.fdr-badge` CSS class-name collision (crest image vs.
difficulty-pill) found again, not fixed. Type-scale tokens (`--fs-*`)
still only applied to Match Centre, not file-wide.

## Where things stand (updated 2026-08-29, forensic visual/product redesign pass)

Direct user instruction: backend is functionally complete, no more
architecture - a pure CSS/markup pass against `https://fpl.page/` as
reference. System Live strip collapsed into a compact status line + a
`<details>` disclosure for the previously-cramped telemetry row (all
existing element ids preserved for the JS poll loop); hero-metric/cross-
check-pill sizing polished. New `--fs-2xs`..`--fs-xl` type-scale tokens in
`legacy.py`'s `:root` (a bounded fix, applied to Match Centre this pass -
NOT a whole-file mechanical rename, real disclosed follow-up). Match
Centre re-audited live via the project's own flip-a-finished-match-to-LIVE
technique: card border/divider, team-colour-filled badges (was outline-
only), pill-shaped muted stat bars (was opaque neon blocks) - momentum
chart/shot map re-verified already solid from an earlier pass, untouched.
Nav bar (intentionally horizontally-scrollable below ~900px) gained a
right-edge fade so users know more tabs exist off-screen - the one real
finding from a 1440/1024/768/390 responsive sweep. Real bug hunt during
the Match Centre re-audit turned up two false alarms (stale pre-fix
Substitution event descriptions on an old match, fixed by a real re-sync
rather than a code change; a name that looked encoding-mangled in the
terminal but was confirmed correct UTF-8 - a codepage artifact, not a
storage bug) - full account: `docs/history/32-session-2026-08-29-forensic-
visual-redesign.md`.

**Genuinely still open** (real, disclosed): the type-scale tokens aren't
applied file-wide yet - most panels outside Match Centre still use ad hoc
rem literals; a real, larger, unattempted follow-up. No GW was genuinely
LIVE at any point this session (all real fixtures today are PRE_MATCH) -
Match Centre verification used the same disclosed temporary-flip
technique as prior sessions, not a real live end-to-end render.

## Where things stand (updated 2026-08-29, live architecture rebuild - milestones 4-6)

Three more real pieces closed in one continuation ("continue everything
left"): **(4) decision hysteresis** (spec section 11) - new `models/
decision_hysteresis.py::stable_current_recommendation`, wired into the
ONE real place the "don't flip-flop on noise" concern actually lives
(`monitoring/dashboard/legacy.py::_compute_primary_verdict`, the
dashboard's single authoritative verdict) - requires a real minimum EV
advantage (5.0 pts), a real confidence floor (MEDIUM+), or real
persistence across >=2 consecutive complete decisions before replacing an
already-stable recommendation. Deliberately NOT wired into `live_
snapshot.py`'s freshness check or `adversarial_audit.py`'s cross-check -
those legitimately want the raw, unfiltered latest decision. **(5) live
feed SSE rendering** - `change_event`/`match_event` SSE channels (built in
milestone 2 but not rendered) now appear in the browser's live-changes
feed, reusing the EXACT SAME dedup-key scheme the existing poll-based feed
already uses (`'chg:'+entity_id+':'+detected_at`) so the same real
`change_events` row delivered twice (once by SSE, once by the next poll)
correctly dedupes; `match_event` (FotMob's own richer per-incident
description) gets its own real key off `match_events.id`, genuinely
additive rather than a duplicate. **(6) provider abstraction** (spec: "a
provider abstraction... so the provider can later be swapped") - new
`providers/football.py` (`FootballDataProvider` Protocol + `FotMobProvider`,
a real class wrapper around the existing FotMob module functions, dynamic
module lookup so existing `monkeypatch.setattr(fotmob_mod, ...)` tests keep
working unchanged) and `providers/fpl.py` (`FplDataProvider` Protocol -
real finding: `ingestion/fpl_api.py::FPLApiAdapter`, built in an earlier
session, ALREADY satisfies this shape; aliased as `OfficialFplProvider`,
zero reimplementation). `sync_match` gained an optional `provider=`
parameter (defaults to `FotMobProvider()`, 100% backward compatible) -
genuine swappability proven by injecting a real fake provider and
confirming it (not the real FotMob functions) gets called. 1291 tests
green (17 new: 8 hysteresis, 5 providers, plus SSE/dashboard regression
coverage). Full account:
`docs/history/31-session-2026-08-29-live-architecture-milestones-4-6.md`.

**Genuinely still open** (real, disclosed): real production verification
against a genuinely live match with the full pipeline active end-to-end
(no GW was live this entire session); the FPL-side event vocabulary
(FPL_POINTS_CHANGED/BONUS_CHANGED) isn't wired onto the event bus yet
(FPL's own live endpoint remains the authoritative source for those,
read directly - not currently republished as bus events); end-to-end
latency instrumentation (spec section 15) not built.

## Where things stand (updated 2026-08-29, live architecture rebuild - milestone 3)

Materiality engine (spec sections 6/7: "do not run the expensive optimizer
for every minor event... injury/availability changes -> full decision
engine update"). New `live/materiality_engine.py` - makes the already-real,
already-tested `cli/main.py::_maybe_trigger_strategic_plan_recompute`
(HIGH-severity `change_events` + squad-mismatch + stale-decision gate,
built in an earlier session) REACTIVE: subscribes to
`AVAILABILITY_CHANGED`/`PLAYER_STATE_CHANGED`/`LINEUP_CONFIRMED`/
`PRICE_CHANGED`/`FIXTURE_CHANGED` on the milestone-1 event bus and fires
the real check the instant one of those events lands, instead of only at
the end of a `run_scheduled` tick. Deliberately does NOT alter the
trigger logic itself (per the standing "don't touch optimizer math"
constraint) - pure routing. Per spec's own routing table, GOAL/ASSIST/
CARD/SUBSTITUTION/SHOT are explicitly NOT routed here (a shot or sub is a
FAST-ENGINE concern, never worth a real 2-10min beam search on its own -
only a resulting AVAILABILITY_CHANGED would trigger one). Registered at
the three real event-producing entry points (`run_scheduled`,
`live_match_poll_cmd`, `refresh_in_progress_matches`). 1278 tests green (4
new) - deliberately does not spawn a real subprocess in tests
(`_maybe_trigger_strategic_plan_recompute` is monkeypatched; its own real
trigger logic is separately covered by `test_strategic_plan_auto_trigger.py`).
Full account: `docs/history/30-session-2026-08-29-live-architecture-milestone-3.md`.

## Where things stand (updated 2026-08-29, live architecture rebuild - milestone 2)

Real-time client transport (spec section 8: "replace the browser-as-
primary-poller model with SSE"). New `live/sse_server.py` + `fpl
live-server` CLI command - a real, stdlib-only (no new dependency)
`ThreadingHTTPServer` exposing `/events` (Server-Sent Events) and serving
the dashboard's static files. Deliberately a SEPARATE real OS process from
`live-match-poll` (per the spec's own "keep the persistent worker and the
dashboard/API separate" allowance) - since milestone 1's in-process event
bus doesn't span processes, `DbTailer` bridges the gap by tailing the
same real, already-persisted `match_events`/`change_events` tables plus
`live_snapshot.json`'s own mtime, translating each genuinely new
row/version into a real SSE push (this is also, by construction, the
real reconciliation mechanism the spec asks for - every push reads
straight from the authoritative DB/file state). The browser's existing
~10s snapshot poll is completely unchanged - it now serves purely as the
real fallback/reconciliation path; a new, minimal `EventSource` connection
(default `http://127.0.0.1:8877/events`) reuses the existing
`applySnapshot` function directly for near-immediate updates when
`live-server` is reachable, and fails silently (auto-retries) when it
isn't - zero regression risk either way. Real bug found + fixed via this
milestone's own tests: a genuinely new row inserted in the narrow window
between server start and the tailer thread's own initialization was
wrongly treated as "already known at startup" (baseline computed too
late) - fixed by capturing the baseline synchronously in `LiveServer.
__init__`, before `.start()` returns. `scripts/setup_live_server_scheduler.ps1`/
`remove_live_server_scheduler.ps1` prepared (not run - a persistent Task
Scheduler change is the user's call) mirroring the existing live-poll
scheduler pattern. 1274 tests green (7 new). Smoke-tested against the
real production `data/` directory (dashboard.html + live_snapshot.json
both served correctly). Full account:
`docs/history/29-session-2026-08-29-live-architecture-milestone-2.md`.

## Where things stand (updated 2026-08-29, live architecture rebuild - milestone 1)

Direct spec: replace ad-hoc "read the DB directly" wiring with a real event-
driven pipeline (provider -> canonical state -> fast/deep engines ->
decision -> dashboard). Milestone 1 (no UI changes): new `events/` package
(`EventType` vocabulary, synchronous in-process `EventBus` - correct scope
for this single-process CLI app, not a distributed broker) and
`live/fast_engine.py` + migration 0036 (`live_player_state` - a real
SUBSTITUTION/MATCH_FINISHED-driven "this player's match minutes are now
locked" fact this project previously computed and threw away).
`fotmob_source.py::sync_match` now diffs against `match_events`'s own real
UNIQUE key to detect genuinely new incidents and publishes typed
GOAL/ASSIST/CARD/SUBSTITUTION/MATCH_STARTED/HALFTIME/RESUMED/FINISHED
events (assist via FotMob's own real `assistPlayerId`); `change_detection.py`
now also publishes PRICE_CHANGED/AVAILABILITY_CHANGED/LINEUP_CONFIRMED/
FIXTURE_CHANGED onto the SAME bus - one real event system, not two. Real
bug found + fixed via this milestone's own deterministic test: a fixture's
very first sync (often already LIVE) never fired MATCH_STARTED. 1267 tests
green (7 new), including a real 3-tick E2E test proving the whole chain.
Full account: `docs/history/28-session-2026-08-29-live-architecture-milestone-1.md`.
**Not done yet, real, disclosed, next milestones**: SSE/WebSocket
transport, FPL-side provider abstraction, materiality-engine
consolidation, decision hysteresis, reconciliation loop, production
verification against a genuinely live match.

## Where things stand (updated 2026-08-29, FotMob data extraction + live Match Centre pass)

Real FotMob investigation (live-tested against actual endpoints): `content.
momentum`/`content.shotmap`/`content.playerStats` were confirmed present in
the SAME `matchDetails` payload `fotmob_source.py::sync_match` already
fetches every sync - real per-minute momentum + per-shot x/y/xG were never
parsed (migration 0035, `match_momentum`/`match_shots` tables), and real
rating/minutes/assists/xA/chances-created were hardcoded to `None` in
`parse_player_states` despite the schema already supporting them. Real bug
found + fixed: the `player_match_state` upsert's `ON CONFLICT DO UPDATE
SET` omitted `rating`, so a re-synced match never refreshed it. New
`monitoring/dashboard/match_centre.py` - real live score/team-stats/
momentum-chart/shot-map/my-players panel, single-sourced from a new
`live_snapshot.py::_active_matches_block` (zero duplicate FotMob fetches),
placed unconditionally near the top of the page (deliberately independent
of the coarser gameweek-level `dash_state`). Real torn-read fix:
`_write_dashboard` now wraps `generate_dashboard_html` in an explicit
`BEGIN`/rollback transaction (confirmed that function's whole call tree is
genuinely read-only) so a concurrent scheduled writer can no longer make
one render combine a new value for one field with an old value for
another. `live-match-poll` default interval tightened 25s->15s. 1257 tests
green (12 new), live-verified by temporarily flipping a real finished match
to LIVE status, screenshotting, and reverting - no GW was genuinely live
this session. Full account:
`docs/history/27-session-2026-08-29-fotmob-live-match-centre.md`.

## Where things stand (updated 2026-08-29, live command centre pass)

Real bug found + fixed: the browser's "Next check" live-poll countdown
could reach 0s and freeze there forever (`nextPollAt` only advanced on a
successful poll; any failed/absent fetch - common outside a live match -
froze it). Readable "Data health · N issue(s)" replaces the old raw
`"N source(s) degraded: fpl_api_my_team, livefpl, ..."` dump (technical
names now only on click/expand). Real chart-legibility fix (`live_charts.py`/
`legacy.py` CSS) - charts could render as small as ~70-90px tall at a narrow
grid column; now floor at 240px with a wider minimum column. Real
flat-vs-gradient design contradiction fixed on the Home hero (was a purple
gradient despite the header's own "flat, no gradient" rebuild). Real FotMob
xG/xA/shots/key-passes (already fetched, never displayed) now shown on
squad players' live match rows; new compact real MATCH STATS panel
(possession/shots/xG/corners, `team_match_state`). 1245 tests green,
live-verified against the real production dashboard. Full account:
`docs/history/26-session-2026-08-29-live-command-centre-pass.md`. No GW was
actually live during this session - the countdown/patch-in-place mechanics
were verified against the live-poll channel's real behavior, not against a
genuinely advancing match.

## Where things stand (updated 2026-08-29, continuation: remaining limitations closed)

Real captain-contribution + starting-XI actual-vs-expected charts (per-finished-GW grain, real
`prediction_outcomes`/`my_team_picks` joins - no new storage). Player Inspector drawer gained a
real MARKET row (`external_benchmark.compare_player`) and a real REVIEW state (reuses `ta.
evidence_confidence`) - BUY deliberately not added anywhere (would violate the "no second
competing recommendation" rule elsewhere in this codebase). News panel now shows the real STATE
CHANGE + MODEL IMPACT a matched news item correlates with (`change_events` within 48h, reuses
the row's own real `fpl_impact` text). Price History's forecast table is now a real `<table>`
(was a flex-row list), matching a genuine structural gap found via direct fpl.page screenshot
comparison - found + fixed a real CSS bug in the process (`.price-progress-track`'s `flex-basis`
was inert outside a flex container). See
`docs/history/25-session-2026-08-29-remaining-limitations-closed.md`.

## Where things stand (updated 2026-08-29, continuation: perf fix + more fpl.page parity)

**Real perf bug found + fixed**: `get_locked_squad()` was running a full ~600-player Dixon-
Coles/Monte-Carlo xP scan on every ~20-25s live-match tick (via `live_snapshot.py`), silently
violating that module's own "stay cheap" contract - `optimization/locked_squad.py::
_xi_from_real_picks` now uses `build_player_pool_for_ids` (scoped to the 15 known picks) instead
of `build_player_pool` (full pool). ~26x faster (6.6s → 223ms for a full `build_live_snapshot()`
call), measured against production. New: Fixture Tool Rotation sort + Reset (real blank/double-
GW detector, no fabricated risk model), Opportunity Board "MY SQUAD IMPACT" (reuses `ta.
candidates`), a real intragame live-rank chart (the decisions journal already logged the time
series - just needed a reader), Player Inspector FOOTBALL section. Dead-CSS audit round 2 found
a second real bug (Opportunity Board's Value cards missing their kind-label color - wrong
selector name). See `docs/history/24-session-2026-08-29-continuation-perf-fix-and-more-parity.md`.
1219 tests green.

## Where things stand (updated 2026-08-29, final product + decision system completion pass)

Real MODEL vs FOOTBALL/MARKET(Solio)/TEMPLATE cross-check (`decision_fusion.captain_cross_check`,
never averaged, one row of AGREE/CONFLICT/DIVERGENCE + WHY) now on the Home hero, right under the
captain verdict. Points Changes carries a real LIVE/EXPIRED status (fpl.page's own published 1h-
lock rule; their real "Pending" state is explicitly NOT built - needs Opta's raw feed, no access)
and is wired into `live_snapshot.json` + the live-changes feed. Chip Strategy now surfaces the
real "why now / best alternative / opportunity cost" explanation `chips.py::schedule_chips`
already computed but no panel read before this. SYSTEM LIVE strip gained real News/Projections
freshness fields. Template Team shows real overlap/differential against the locked squad.
Gameweek Projections got a real 3/5/8GW range toggle. Audited several other spec asks (fake
countdowns, live-change feed, strategy-family clustering, burst-coalescing) and found them
already solved by prior sessions - verified, not rebuilt. Full account:
`docs/history/23-session-2026-08-29-final-decision-system-completion-pass.md`. 1211 tests green.

## Where things stand (updated 2026-08-29, fpl.page-parity P1 features pass)

Six fpl.page-parity dashboard features closed - Points Changes (new), Template Team + real
sampled-EO margin of error, league-wide Price History (search/filter/progress-bar + confirmed-
change ledger), news decision-impact tags, Fixture Tool Goals/CS% view toggle - plus the
outstanding responsive-QA breakpoints and a dead-CSS/dead-function cleanup pass. See item 13
under "Next recommended work" and `docs/history/22-session-2026-08-29-fpl-page-parity-p1-features.md`
for the full account. 1197 tests green, live-verified against production via a real localhost-
served dashboard render.

## Where things stand (updated 2026-08-29, master live + strategic-plan correction pass)

**Real, confirmed root-cause bug found + fixed: `decision: null` in the dashboard's own
`workspace-data` JSON.** A `fpl strategic-plan --no-current-action` search-diagnostic run (the
beam-width 5/10/20/50 experiment, CLAUDE.md's own known-blockers entry) had become the LATEST
`strategic_plan` decision in production (decision #115) - every consumer that blindly trusted "the
single latest strategic_plan decision" (dashboard primary verdict, workspace JSON, live snapshot
freshness/change-explanation, adversarial-audit cross-check) inherited its real, honest
`current_recommendation: null` and silently went blank. Fixed with one shared helper,
`optimization/strategic_planner.py::latest_strategic_plan_with_recommendation`/
`strategic_plan_decisions_with_recommendation` - skips past any incomplete decision to the latest
genuinely COMPLETE one, wired into all 6 real call sites (`legacy.py` x2, `live_snapshot.py`,
`adversarial_audit.py`, `decision_change.py`, plus a new self-healing auto-trigger condition in
`cli/main.py::_maybe_trigger_strategic_plan_recompute`). Live-verified: the rendered dashboard's
`workspace-data` JSON now carries a real, non-null `decision` object (decision #102, PLAY WILDCARD,
path_total=628.55) instead of `null`.

**Real, confirmed root-cause bug found + fixed: a wildcard/freehit step carried NO squad
information at all.** `optimization/transfers.py::TransferSequenceStep` had no field for the
optimizer's own real rebuilt squad - `chip_gw_marginal_value` (`chips.py`) always computed a real,
legal, budget-respecting rebuild via `optimise_squad`, but discarded it on the way out for display
purposes (only `new_squad_ids`, which is `None` for freehit by design - a one-GW rental that must
NOT persist - was ever threaded through, and even that never reached the STEP itself). The
dashboard's own squad-state reconstruction (`_squad_state_by_event`) replayed `player_out_id`/
`player_in_id` pairs, which a chip step never has, so it silently carried the PREVIOUS gw's squad
forward and displayed it as the wildcard's own team. Fixed: `TransferSequenceStep.resulting_squad_ids`
(always populated - roll/transfer/chip alike) and `StartingActionOption.starting_squad_ids` (the
real per-GW DISPLAY squad, distinct from `resulting_squad_ids` for freehit specifically) now carry
the optimizer's real rebuild end to end - `chips.py`, `transfers.py` (`search_transfer_sequences`,
`compare_starting_actions`, `_synthetic_sequence_from_option`, `path_detail`), `legacy.py::
_squad_state_by_event` (now reads the real field directly, replay logic kept only as a fallback for
a decision logged before this field existed). Also added `ChipStepResult.rebuild_failed` - a
wildcard/freehit branch whose rebuild genuinely fails (infeasible budget/constraints) is now SKIPPED
entirely, never offered as "PLAY WILDCARD" with the current squad silently relabeled (direct user
instruction). Live-verified in the real rendered browser: clicking the GW2 WILDCARD timeline node
shows a genuinely different 15-man squad (Kinsky/Ajer/Ballard/Calafiori/Maguire.../B.Fernandes
captain, 47.4 projected pts) from the current squad; clicking GW3's transfer node shows "OUT Ajayi —
2.2 xP / IN Guéhi — 6.8 xP / Net player projection: +4.7 xP" and a DIFFERENT GKP than GW2 (real
per-GW XI re-resolution, not carried forward).

**Real per-player xP now shown on every future-GW tile** (`squad.py::_projected_shirt_tile`, reuses
`resolve_projected_xi`'s already-computed per-player median, zero new computation) and a real OUT/IN
xP + net-delta line on every transfer step (reuses `build_player_pool_for_ids` with the same shared
`xp_cache`, since the OUT player may not be in the resulting squad).

**Real path-score traceability**: `TransferSequenceStep.gw_ev` (post-hit-cost, same convention
`StartingActionOption.starting_gw_value` already used) is now populated at every branch -
`sum(step.gw_ev for step in steps) == path_total` exactly, a real invariant now covered by
`test_path_total_equals_sum_of_step_gw_ev` against the actual joint search output (not a
hand-constructed fixture).

**Real, always-honest "SYSTEM LIVE" freshness strip** (`home.py::_system_live_html`, CSS in
`assemble.py`) - a static shell populated and kept live entirely by the SAME `live_snapshot.json`
poll already driving the rank/points tiles: real snapshot age, decision age, rank age, and a
degraded-source count, all ticking client-side off REAL stored timestamps (`Date.now() - stored`),
never a fabricated counter. Also added a real rank Δ badge (diff between two real observed polls,
blank until a second real observation exists this session - never a fake Δ0). **Real, disclosed
scope limit**: only snapshot/decision/rank age are wired into the strip; bonus/DEFCON/squad/
per-source next-due countdowns (the full "central freshness registry" ask) are NOT built this pass -
`source_freshness` is already in the snapshot JSON (2026-08-28) but not yet surfaced per-source in
this strip. A full per-source `next_due` also isn't derivable cleanly from `config/freshness.yaml`
today (semantic categories like `fixtures`/`price`, not 1:1 with real `source_health.source_name`
values) - a real, scoped follow-up, not attempted this pass.

**Real operational finding, not fixed (blocked by this session's own safety tooling)**: while
live-verifying against the real production machine, found `FPLAgentLivePoll`'s registered process
had been running continuously since well before this session's fixes landed (a long-lived Python
process holds its imports in memory - editing `.py` files on disk doesn't affect an already-running
interpreter). Restarted the scheduled task via `Stop-ScheduledTask`/`Start-ScheduledTask`
(succeeded), but the OLD process didn't actually terminate and a NEW one now runs alongside it -
attempting to `Stop-Process -Force` the stale PIDs was blocked by this session's own auto-mode
safety classifier. Both share the same `data/live_snapshot.json` file (each write is atomic, so no
corruption risk, just "whichever wrote last wins" each cycle) - real, honest, user-visible
consequence: the SYSTEM LIVE strip's Decision/Rank fields showed "no decision logged yet"/
"unavailable" during verification even though the underlying code is fixed and independently
verified correct (a direct, controlled `write_live_snapshot` call in this same session produced the
correct non-null values). **Action needed from the user**: end the stale `fpl.exe live-match-poll`
process (Task Manager, or simplest - a laptop reboot) so only the current-code instance remains.

**Not attempted this pass, honestly disclosed**: a persistent "LIVE CHANGES" feed strip (P0 ask);
intragame (sub-GW) time-series storage for the live charts to work mid-match before 2 completed GWs
exist (P0 ask - the two existing charts still correctly gate on `my_team_gw_summary`, which is only
per-finished-GW); per-source next-due countdowns beyond snapshot/decision/rank; real descriptive
path names beyond "Path N" (P1); a from-scratch restart/overnight verification (partially covered by
the Task Scheduler stop/start above, not a full laptop-off-to-on cycle). Each is real, scoped,
comparable in size to its own session - not attempted rather than rushed.

## Where things stand (updated 2026-08-29, live product loop completion pass)

Extended `monitoring/live_snapshot.py` to real full coverage per the "one live authoritative
snapshot" audit: `gw` (lifecycle event/state), `squad` (every squad player's slot/captain/vice/xp/
availability classification in one array, reusing `models.availability.classify`), `match_events`
(goals/assists/red cards, sharing one `compute_live_bonus` call with the existing `bonus_defcon`
block rather than a second live-payload pass), and `source_freshness` (every `source_health` row
with a plain `failure_count>0` degraded flag). `models/decision_change.py`'s
`DecisionChangeExplanation` gained a real `impact` field (new `path_total` minus old, both real
full-horizon EV) — `fpl decision-changes` now prints OLD/NEW/TRIGGER/IMPACT/TIME, not just three
of the four. Browser-side: the existing 20s `live_snapshot.json` poll (2026-08-28) now also patches
the Home hero's RECOMPUTING banner/action-word in place the moment a real HIGH-severity change
lands, reusing the server's own `home-hero-stale-banner` CSS class rather than inventing new visual
design — live-verified this doesn't regress the two staleness-banner dashboard tests (fixed a real
test-precision gap those tests had: a bare `"RECOMPUTING"` substring check now also matches the
always-shipped poll script's own JS string, so both tests were tightened to check for the actual
server-rendered `<div class='home-hero-stale-banner'>` tag instead). Bonus/DEFCON/squad/match-events/
source-freshness are in the snapshot but NOT yet browser-patched — real, disclosed, scoped follow-up
(the full-regen/meta-refresh cadence already covers them correctly, just not sub-20s).

Built real, data-driven **live charts** (`monitoring/dashboard/live_charts.py`): rank trajectory +
cumulative GW points, both single-sourced from `my_team_gw_summary` (real official per-GW FPL data,
no new ingestion), inline SVG, wired into the existing `#live` panel. Deliberately NOT built this
pass (data sources identified, not implemented): squad contribution / captain contribution / actual-
vs-expected — all three need a `prediction_outcomes` + `my_team_picks.is_captain` join that wasn't
built and verified this session; shipping 2 solid charts beats 5 unverified ones.

**Understat repair prioritization, quantified not guessed** (per-season real query against
`player_match_stats_history`): 2021-22 7855/10485 unresolved, 2022-23 7333/11345, 2023-24
6767/11384, 2024-25 5774/11567, 2025-26 2617/11490 (down from 4222, the one season already
repaired 2026-08-28). Real reason 2025-26 stays highest-value and the other four stay
deprioritized: `_hierarchical_prior_rates`/`_hierarchical_share_prior` (the live model's own
shrinkage-prior fallback) only ever reads the single most-recent prior season — 2021-22 through
2024-25 currently have ZERO measured effect on live projections, and only matter for a future
multi-season-pooling change (real, deferred, see CLAUDE.md's own bonus-regression follow-up note)
or a from-scratch historical backtest of that specific season. Not re-run this pass (would mostly
re-fetch matches already confirmed genuinely unresolvable — players long removed from the live
roster — near-zero new yield); real next action is a fresh `fpl repair-understat-players --season
2025-26` batch to chase the remaining 2617, not the older seasons.

**Decision-outcome backtest (`fpl decision-backtest`), verified not rebuilt**: already preserves
every real deadline-freeze snapshot (`record_decision_snapshot`, idempotent per event/season/kind)
and already auto-reveals on GW finish (post-GW pipeline). `n<5` already reports as "not enough real
samples to claim statistical significance" alongside the real row, never blocking/hiding output —
matches this pass's ask exactly, no code change needed.

**Assist/bonus correlation — backlog item added, not rewritten** (per the standing "quantify before
rewriting" rule): the measured 7% same-team assist-draw violation rate (2026-08-28) still hasn't been
checked against whether it actually flips a real captain/transfer/BB/FH/TC decision anywhere in
production — a real, scoped, next-session question (does the 7% correlation gap ever move a decision
past its materiality bar, or is it noise the decision layer already absorbs) rather than a modeling
rewrite.

## Where things stand (updated 2026-08-28, decision-outcome backtest + Understat repair + live-state completion pass)

Built the real decision-outcome backtest (`models/decision_calibration.py`, migration 0034,
`fpl decision-backtest`): captures the recommended action + best real rejected alternative at
each real deadline freeze (wired into `run_scheduled`'s existing LOCKED-lifecycle trigger),
reveals real actual outcomes once the gameweek finishes (wired into the post-GW pipeline).
Real first sample captured against production for GW2 (pre-deadline, non-hindsight); reveal
happens automatically once GW2 finishes.

Started (not finished) the historical Understat player-id repair: `ingestion/understat_source.py
::repair_unresolved_player_ids` safely re-fetches real match pages and re-resolves via the
existing team-scoped fallback - no fabrication, zero duplicate-row risk. Real production run for
the highest-value season (2025-26): 1605/4222 rows resolved (38%). Confirmed real downstream
effect: Bruno Fernandes' own last-season data is now fully resolved, and he dropped out of the
top Solio-divergence list. Older seasons (2021-22 to 2024-25) not yet repaired.

Extended the live snapshot channel with bonus/DEFCON, recent squad-relevant changes, and decision
freshness + a real "why did the recommendation change" explanation (`models/decision_change.py`,
`fpl decision-changes`). Quantified (not fixed) the remaining assists/bonus correlation gap: a
real but smaller 7% same-team violation rate for assists (vs goals' 34% before that fix) -
judged not yet material enough to justify building the missing "share of team assists" primitive
this pass, per the standing "quantify before rewriting" instruction.

## Where things stand (updated 2026-08-28, correlation + backtest-wiring + live-perf pass)

Real correlation bug found + fixed in the Monte Carlo scenario engine: two+ squad-tracked
teammates sharing a fixture drew independent goal counts, provably double-counting the same
real goal in ~34% of stress-tested trials. `scenario_sampling.py::sample_team_group_trial_points`
jointly multinomial-attributes the shared team_goals draw across them instead. A real perf bug
found + fixed in `live_match_poll_cmd`: it was calling the full ~1-minute `generate_dashboard_html()`
on every ~25s tick during a live match, starving its own configured interval. New
`monitoring/live_snapshot.py` writes a cheap `data/live_snapshot.json` every tick instead; the
dashboard's own JS polls it every 20s and patches the live-rank/live-points tiles in place -
live-verified in a real browser session, zero page reload. The full dashboard now only
regenerates on a real FULL_TIME transition during that loop.

Also found + fixed a real backtest-wiring gap: `backtesting/harness.py::run_backtest` never
actually called the code path the 2026-08-27 hierarchical-prior fix lives in (a stale docstring
elsewhere falsely claimed it did) - wiring it in properly surfaced a real, valuable finding:
applied unconditionally, the fix was net-harmful (~1% MAE regression) once a player already has
4+ real current-season matches. Gated to `_MIN_MATCHES_FOR_HIERARCHICAL_PRIOR=4` matches (both
the goals/xa rate prior and the share-of-team-xG prior) - real production case (Haaland/Bruno,
matches_played=1) is unaffected by the gating.

Audited (not restructured) the live dependency-recompute chain: the existing two-tier split
(cheap live decision layer every regen + expensive strategic-plan gated behind a real
materiality check) already satisfies "don't run the whole optimizer for every source update" -
a fully staged per-entity dependency graph doesn't exist and would be a real, separate,
larger project. Decision-outcome backtest and Solio historical comparison remain unbuilt -
the latter is structurally impossible (Solio's endpoint is live-only, no historical API).

## Where things stand (updated 2026-08-28, projection-model root-cause fix pass)

Two real, confirmed modeling bugs found and fixed via direct root-cause tracing against the
Solio benchmark (never tuned toward Solio's numbers - see CLAUDE.md's known-blockers entry for
the full account): (1) a shrinkage-prior cutover bug that discarded a player's real, larger
prior-season goals/xa record the instant they had even one current-season match, and (2) an
unshrunk player-share-of-team-xG bug (the actual dominant driver for Bruno Fernandes'
divergence) that let a single quiet match fully determine a player's attacking share. Fixed in
`models/expected_points.py` (`_hierarchical_prior_rates`, `_hierarchical_share_prior`) and
`models/player_regression.py` (`player_shrunk_rates`' new `prior_overrides` param). Real
production result: Bruno's divergence vs Solio narrowed from +95% to +30%; several previously-
outlier players now show AGREEMENT. A real, large, disclosed data-quality gap was found in the
process (56.5% of historical `player_match_stats_history` rows have unresolved `player_id`,
predating the 2026-08-26 name-matching fix and never retroactively repaired) - explains why
Bruno specifically still shows MATERIAL_DIVERGENCE rather than AGREEMENT; needs its own
re-scrape-based repair session, not fixed this pass. Search-width experiment (beam 5/10/20/50)
confirmed beam_width=5 is stable (identical top path at every width) - kept as-is. 8 new tests,
full suite green (1122 tests).

## Where things stand (updated 2026-08-27, Solio benchmark pass)

**Independent-model benchmark against Solio Analytics** (public, no-auth `fpl.solioanalytics.com/api/data/latest.json`,
live-verified) - `ingestion/solio_source.py` (fetch/crosswalk/store, self-throttled to Solio's own ~4h cadence,
wired into `run_scheduled`), `models/external_benchmark.py` (AGREEMENT/MINOR/MATERIAL/MAJOR_OUTLIER divergence
classifier + real component-level attribution reusing `expected_points()`'s own `ComponentBreakdown`, captain/
transfer-target cross-check against the real `decision_analysis` output - never re-derives or overrides it),
`fpl solio-sync`/`fpl model-benchmark` CLI, and a compressed (never raw-JSON) Advanced-drawer dashboard panel
(`monitoring/dashboard/benchmark.py`). Real production run: 62/62 GW2 players and 12/12 teams crosswalked with zero
misses; team-level clean-sheet probabilities agree closely across the board (real cross-model sanity check); found
one real, investigated, NOT auto-corrected divergence (B.Fernandes MAJOR_OUTLIER, traced to early-season
per-90-rate shrinkage on a 1-match sample - see CLAUDE.md's known-blockers entry) and one real AGREEMENT (current
transfer target Tavernier also appears in Solio's own top lists). 38 new tests (ingestion, divergence
classification, component attribution, decision cross-check, dashboard rendering, CLI).

## Where things stand (updated 2026-08-29)

Dashboard: chip rendering (Plan timeline, Squad preview) is now single-sourced from each path's
own `steps[].chip_played` - never the separate `schedule_chips` DP cross-check, which could
(and did) disagree on GW/chip. Home hero discloses the cached strategic-plan decision's real age
(`Computed Xh ago · decision #N`) and shows an explicit RECOMPUTING banner when a real HIGH-
severity `change_events` row postdates it (`models/decision_freshness.py`). Squad workspace's
projected future-GW squads now resolve a real starting XI/bench order/captain/vice per specific
GW (`optimization/squad.py::resolve_projected_xi`), not carried over from the current squad.
Plan's top-N paths are now built from `compare_starting_actions`' real per-starting-action options
(`optimization/transfers.py::build_diverse_paths`), not the raw beam's own top-N (which provably
converged to near-duplicate variants of one dominant opening move) - each displayed path now has a
genuinely different first action, plus a real 3/5/8GW `horizon_breakdown` (total/delta-vs-roll/
delta-vs-next-best per checkpoint, `checkpoint_breakdown`). Opportunity Board cards show a real
"considered by optimizer" flag (against the same diverse-paths candidate pool) and Value no longer
shows a card for a player already in the squad (matches Breakout's existing exclusion). Fixed a
real intermittent "dashboard shows no squad" bug - a torn read in `ingestion/my_team.py::get_latest_squad`
racing against the project's own scheduled sync writer (`docs/history/20-...md`).

**The optimizer now runs automatically (2026-08-29)** - `run_scheduled` fires a real `fpl
strategic-plan` as a detached background subprocess whenever a real material change (HIGH-severity
`change_events` on a squad player, or the locked squad itself diverging from what the last plan was
computed against) has happened since the last cached decision (`cli/main.py::_maybe_trigger_strategic_plan_recompute`).
Live rank now refreshes on a genuine ~5min cadence during an active GW (`live-match-poll`'s own fast
loop, not the slower `run_scheduled` cadence). `fpl scheduler-status` reports both real registered
daemon tasks, not just one. See `docs/history/21-...md` for the full real architecture audit (most
of a much larger automation/optimizer spec was found already built - minutes model, correlated
scenario sampling, adaptive scheduler cadence, calibration capture - rather than needing new code).


**Season**: 2026-27, GW1 finished (all 10 fixtures analyzed, real qualitative evidence recorded for Arsenal-Coventry and league-wide via the zero-LLM statistical detector), GW2 not yet locked (real fixtures scheduled ~Aug 29-Sep 1). Real locked squad synced (entry 7378572, `fpl my-team`).

**System capability**: full pipeline from raw data → calibrated projections → multi-GW strategic planning → dashboard, running autonomously via the Windows Task Scheduler. Real free-transfer state, real chip-usage detection, real qualitative evidence (LLM + zero-LLM), real confidence/robustness/uncertainty reporting, real 1/3/5/8-GW path search with joint chip+transfer optimization (chips compete inside the beam, not a post-hoc overlay), a real full-squad starting-action comparison producing one authoritative CURRENT RECOMMENDED ACTION, a real Squad workspace (per-path/per-GW squad reconstruction, CURRENT/GW pill switcher), real Model-vs-Football-vs-User-view fusion, a real Adversarial Decision Audit (`fpl decision-audit`) that tries to disprove the current recommendation - causal trace, named-player MODEL-vs-FOOTBALL comparison, analytic counterfactual-stress falsifiers, multi-horizon (3/5/8GW) alternative-action audit, league-wide breakout/differential/trap check, cold-start coverage, qualitative-evidence chain, and a final trust/no-trust scorecard - cached in the decisions journal and surfaced as a compact "WHAT CHANGES IT" line + collapsed full trace under Advanced -> Decision Detail.

## Strategic planner status

`optimization/strategic_planner.py` + `optimization/transfers.py::search_transfer_sequences` — real beam search (default beam width 5, horizon 8 GW), scores full-squad EV summed across the horizon, jointly chip-aware (wildcard/freehit/bboost/3xc compete against ROLL/TRANSFER on the same ranking key at every step, `optimization/chips.py::chip_gw_marginal_value`). `chips.py::schedule_chips`'s Monte Carlo DP (`--with-chips`) is an independent cross-check/opportunity-cost narrative, not the path-selection mechanism. `search_transfer_sequences`/`best_transfer_for_player` price hit cost using the real FT state (`models/free_transfers.py`).

`optimization/transfers.py::compare_starting_actions` + `optimization/strategic_planner.py::synthesize_current_recommendation` compare every real starting action (ROLL, each squad player's best replacement, each legal chip) against its own best full-horizon future and produce one authoritative `CurrentRecommendation` (ACT/REVIEW, same evidence-confidence gate `decision_analysis.py` uses). Surfaced via `fpl strategic-plan --current-action` (default on) and the dashboard's Home hero + Plan workspace. Real production run (locked squad, 8GW horizon): ROLL wins over the immediate 1-GW pick and over PLAY WILDCARD/FREEHIT, consistent with the main search's own top path.

## Decision-object architecture

`optimization.decision_analysis.analyze_transfer_decision`/`analyze_captain_decision` are the single real source of truth for "what should I do." `optimization.decision_engine.evaluate_locked_squad` is a thin KEEP/CHANGE wrapper that derives its answer from an already-computed `ta`/`ca` rather than re-scanning. The dashboard's Home hero (`#home`) and Plan workspace (`#plan`) are the only two places a recommendation renders (frontend redesign, 2026-08-27 - `monitoring/dashboard/home.py`/`plan.py`, replacing the old Primary Decision panel/Strategy Explorer); every other panel either reads from these or is explicitly labeled as answering a different question (Optimizer Delta = from-scratch rebuild comparison, collapsed under Advanced).

## Free-transfer tracking

`models/free_transfers.py::compute_real_free_transfers` replays the real, public FPL accrual rule over already-ingested `my_team_gw_summary.event_transfers` + `my_team_picks.active_chip` history. Returns `None` (never a guess) on a genuine gap in synced history. Wired into `LockedSquadState.free_transfers`, consumed by `analyze_transfer_decision`/`_evaluate_transfer`.

## Known gaps (see CLAUDE.md's "Current known blockers" for the full, current list)

Summarized: Dixon-Coles team-strength ridge (`_RIDGE_LAMBDA=2.5`, fixes a real small-sample-promoted-team overfit) not yet backtest-tuned; bonus/BPS season-grain only; single predicted-lineups source; sampled-EO margin of error computed but not surfaced; cross-league coverage partial (~5 leagues); manager-change signal not wired into prior-shrink speed; team-level qualitative signal deliberately not fed into Dixon-Coles (leakage-safety); Elite-manager panel needs a season to end; penalty-duty adjustment gated on sample size (2 of 20 needed); dashboard regen ~1 minute; `fpl strategic-plan --current-action` (default on) adds real extra cost on top of that (~2-10+ min depending on horizon/beam-width) — a manual command's cost, never re-run live by the dashboard.

## Next recommended work (real candidates, not started)

1. **Path-diversity - done 2026-08-29** (see `docs/history/19-session-2026-08-29-path-diversity-and-p1-audit.md`): `build_diverse_paths` replaces the raw beam's near-duplicate top-N with `compare_starting_actions`' real per-starting-action options - live-verified against a fresh production run (decision #102): 5 genuinely distinct opening moves (PLAY WILDCARD/PLAY FREEHIT/3 different named-player transfers), not the old single dominant-strategy cluster.
11. **Per-path 3/5/8-GW breakdown - done 2026-08-29**: `checkpoint_breakdown` (bounded to the selected top-N paths only, reuses the shared EV cache) - live-verified real signed `delta_vs_next_best` per checkpoint (positive for whichever path actually leads AT that horizon, not assumed to match the full-horizon leader).
2. **Value-of-information folded into `compare_starting_actions`' own ranking**, not just the single-swap decision's separate `information_value_note`.
3. **Team-level qualitative → projection propagation**, done safely (an xG-regression supplement on `team_match_state`, not touching the Dixon-Coles fit itself).
4. **Manager-change → prior-shrink wiring** — a real, scoped, previously-deferred fix.
5. **Surface sampled-EO margin of error** in the dashboard/CLI (currently derived, never printed).
6. **Decision-outcome calibration - done 2026-08-28**: `models/decision_calibration.py`, `fpl decision-backtest` - real deadline-freeze capture + auto-reveal on GW finish, first real GW2 sample captured (pre-deadline, not yet revealed). Still real, scoped work: squad/captain-contribution + actual-vs-expected live charts (data sources identified 2026-08-29 - `prediction_outcomes` + `my_team_picks.is_captain` - not yet built); assist/bonus's 7% correlation gap's real decision-impact (does it ever flip a captain/transfer/BB/FH/TC call, or is it noise the decision layer already absorbs) - not yet checked.
7. **Frontend redesign Phase 2 - done 2026-08-28** (see `docs/history/14-session-2026-08-28-frontend-redesign-phase2.md`): Intelligence workspace now a real league-wide team-signal briefing (`intelligence.py`, calls `team_outlook` across every real team, not just the squad's), Opportunity workspace redesigned into a real scouting board with real confidence per card and a 1-visible-plus-details-for-more cap per category (`opportunity.py`), Market workspace re-framed (`market.py`), Fixture Tool gets real range/metric(overall-attack-defence)/sort/filter controls (`fixtures.py`, reuses the already-built `models.fixtures.fixture_difficulty` - honestly discloses the current preseason attack/defence-strength-not-yet-published fallback). `legacy.py`'s now-fully-superseded orchestrators (`_intelligence_summary_html`/`_opportunity_board_html`/`_market_summary_html`/`_fixture_ticker_html`) deleted, not left dead.
8. **Frontend redesign Phase 3, partially done 2026-08-28**: Squad's projected-GW previews now use real shirt tiles grouped by position (was plain text rows) - see `docs/history/15-session-2026-08-28-visual-density-and-accuracy-audit.md`. Still not done: the `monitoring/dashboard/` module split (legacy.py is still ~4500 lines, mostly Advanced-drawer/Live/Team-Outlook/Match-Intelligence renderers). Fixture Tool's Attack/Defence metrics will start genuinely differentiating from Overall automatically once FPL publishes real attack/defence strength ratings (no code change needed, just currently coincide via an honest, disclosed fallback).
9. **Data sourcing investigation, done 2026-08-28** (see same history file): elevenify.com and Spreadex - the two sources fpl.page itself credits for its projections - are both confirmed NOT viable as automated backend sources for this project (elevenify: single-person Substack, no API/feed, subscription-gated; Spreadex: licensed spread-betting operator, no stable public market data without an account). This project's own Tier-1/2 pipeline (official FPL API, Understat, the-odds-api, BBC/Sky RSS, FotMob) remains the real, disclosed, automatable one - genuinely different methodology from fpl.page's, not a lesser one.
10. **Four new league-wide dashboard panels, done 2026-08-28** (direct fpl.page screenshot comparison - see `docs/history/17-session-2026-08-28-new-panels.md`): Injuries (`injuries.py`, reuses `models.availability.list_availability`), Expected Data (`player_data.py`, real current-season xG/xA/xGI from `player_match_stats_history`), Team Odds and Top Transfers In/Out (`market.py`, league-wide rankings from already-real data). A real historical Odds Tracker line chart is still not built - needs periodic odds snapshotting into a history table, which doesn't exist yet.
9. **Dashboard visual/typography QA at all target breakpoints, done 2026-08-29** (1440/1024/768/360px verified this pass on top of the existing 1280/375 coverage - see `docs/history/22-...md`): zero real page-level horizontal overflow at any width; the two elements a naive scan flagged (`.site-nav`, `.fdr-grid`) are intentional `overflow-x: auto` scroll containers, not bugs.
12. **Opportunity Board "considered by optimizer" flag + Value squad-member exclusion - done 2026-08-29** (see `docs/history/19-session-2026-08-29-path-diversity-and-p1-audit.md`): every card now shows a real yes/no against the diverse-paths candidate pool (never rendered when no strategic plan has run); Value no longer shows an already-owned player as a buy opportunity (real live-screenshot QA finding, matches Breakout's existing exclusion).
13. **P1 product-gap audit, done 2026-08-29; 6 of the "genuinely still unbuilt" items closed 2026-08-29** (see `docs/history/22-session-2026-08-29-fpl-page-parity-p1-features.md`): Points Changes (new - real post-match Bonus/DefCon revision ledger, `models/points_changes.py`, `fpl points-changes`), Template Team + elite-manager context (`template_team.py`, real sampled-EO margin of error surfaced, honest raw-ownership fallback), Price History (`price_history.py`, league-wide search/filter/progress-bar forecast + real confirmed-change ledger, replaces the old squad-only panel), news decision-impact tags (captain/transfer-out/transfer-in, `_news_html`), Fixture Tool Goals/CS% view toggle, dead-CSS/dead-function cleanup (26 CSS rules + 2 functions, scripted audit). **Genuinely still unbuilt**: Top 10K context beyond template/EO, an article feed, a full unified single-view Market redesign beyond the current section-grouped layout, Fixture Tool's "Sort by Rotation" (fpl.page's own metric - no real rotation-risk data source exists per-team to back one honestly; Easiest/Hardest/Squad-first/A-Z sort already exist), Player Inspector click-through redesign (WHY BUY/HOLD/SELL), and decision-outcome calibration (blocked on a season with completed GWs).
14. **Final decision-system completion pass, done 2026-08-29** (see `docs/history/23-session-2026-08-29-final-decision-system-completion-pass.md`): real MODEL vs FOOTBALL/MARKET(Solio)/TEMPLATE cross-check on the Home hero, Points Changes real LIVE/EXPIRED status wired into `live_snapshot.json`, chip strategy why-now/best-alternative explainability, SYSTEM LIVE News/Projections fields, Template Team overlap/differential, Gameweek Projections 3/5/8GW range toggle. **Genuinely still unbuilt, disclosed**: Player Inspector's full BUY/HOLD/SELL/WATCH/REVIEW vocabulary (current per-player inspector is squad-scoped, narrower); intragame live-chart time-series storage (rank/GW-points/squad-contribution/captain-contribution/actual-vs-expected - real, larger infra work, own future session); Fixture Ticker rotation analysis (no real rotation-risk model exists - checked, not faked); full Intelligence-panel editorial restructuring and a structured News→Decision pipeline beyond this pass's own captain/transfer news tags; a dedicated visual-redesign audit against fresh fpl.page screenshots.

## Verification procedure (run before trusting any change to the decision layer)

```bash
# 1. Full test suite - must be green
./.venv/Scripts/python.exe -m pytest tests/ -q

# 2. Real strategic plan against the real production DB
./.venv/Scripts/fpl.exe strategic-plan

# 3. Real dashboard regen - confirm it completes and note the wall-clock time
./.venv/Scripts/fpl.exe dashboard

# 4. Serve it over localhost (NOT file://) and inspect visually in a real browser
python -m http.server 8899 --directory data
# open http://localhost:8899/dashboard.html, screenshot at 1440/1024/768/390/375/360px

# 5. Real production acceptance check: does `fpl transfer-analysis` / the
#    dashboard's Home hero agree, and can you answer "what
#    should I do for GW2, and why" within 5 seconds of opening the page?
./.venv/Scripts/fpl.exe transfer-analysis
```
