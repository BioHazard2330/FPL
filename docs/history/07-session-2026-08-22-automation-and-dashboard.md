<!-- Moved from CLAUDE.md during the 2026-08-27 documentation cleanup pass. Full session narrative, kept verbatim for reference - not required reading for day-to-day work. See docs/PROJECT_STATE.md for current state. -->

## Automation lifecycle: finish the daemon so Claude isn't manually invoked (2026-08-22, continuation session)

Direct 10-point user spec: finish wiring the already-built daemon pieces (run-scheduled,
live-match-poll, predicted-lineup sync, the qualitative-analysis queue) into one
authoritative gameweek lifecycle, with a real predicted-vs-confirmed lineup
distinction, an automatic post-GW pipeline, and a dashboard that switches to a
real "results -> next GW plan" view - all without ever requiring Claude Code to
stay open or calling a paid/LLM service from the daemon itself. Went through
plan mode first (multi-file, architectural); the user rejected the first two
plan drafts with two real, concrete correctness demands before approving the
third - both genuinely changed the design, not just phrasing:

- **"Do not declare a GW finished unless the fixture set is complete, every
  fixture resolved, nothing missing, and the sync itself isn't in an invalid
  state."** Added `models/gw_lifecycle.py::_fixture_data_is_trustworthy()` as a
  hard precondition checked BEFORE any "all finished" conclusion: real fixture
  rows exist for the event (guards the classic `all([]) == True` vacuous-truth
  trap explicitly), every row's `finished` value is non-NULL (defensive - the
  schema's own NOT NULL constraint already guarantees this, kept anyway as
  redundancy against a hypothetical future relaxation), `source_health.
  fpl_api_fixtures.failure_count == 0` (the same DEGRADED signal `fpl doctor`/
  `readiness` already use elsewhere), and the event's own row resolves cleanly.
  Any one failing keeps the state at LIVE/LOCKED/UNKNOWN - GW_FINISHED-family
  states are structurally unreachable otherwise. Live-verified: degrading
  `source_health` on an otherwise-fully-finished real fixture set correctly
  keeps the state at LIVE, not GW_FINISHED.
- **"With Claude Code completely closed, prove the daemon alone executes the
  post-GW pipeline - no manual CLI/Claude invocation."** Real problem found
  while designing this test: a genuine subprocess run of `fpl run-scheduled`
  against a scratch DB copy would have its own first step (`run_sync()`, a
  real live FPL API call) immediately overwrite the test's artificially-
  marked-finished fixtures with the real, still-not-finished live data before
  the pipeline check ever ran - the live world genuinely hasn't reached
  GW_FINISHED yet, so a network-connected subprocess test can't fully prove
  this today. Solved honestly, not by weakening the test: added a real,
  permanent, network-free CLI entry point (`fpl post-gw-pipeline`, see below)
  that calls the exact same `maybe_run_post_gw_pipeline` the daemon already
  calls automatically, with no sync step in front of it - a genuine, isolated
  proof of the pipeline logic itself, not a workaround.

### 1. Lineup automation - real predicted-vs-confirmed distinction

- **Real, live-confirmed discovery this session**: FotMob publishes a genuine
  confirmed starting lineup BEFORE kickoff - checked directly against the real
  DB: `player_match_state` already had ~11 real rows per team for fixtures
  still hours from kickoff, while `match_intelligence.status` was still
  `PRE_MATCH`. This was already being ingested (`sync_match`, part of the
  already-built Slice A) but never surfaced as a distinct "confirmed" signal
  anywhere - only the pundit-prediction sources (`predicted_lineups_source.py`/
  `lineup_probability_source.py`) drove the dashboard's old lineup badge.
- **`models/lineup_state.py`** (new) - `resolve_lineup_state`/`squad_lineup_states`,
  real priority order: `players.status` (Tier 1 `OUT_UNAVAILABLE`) beats a
  confirmed lineup (`CONFIRMED_STARTING`/`CONFIRMED_BENCHED`, from
  `player_match_state` presence) beats a mere prediction (`PREDICTED_START`)
  beats `UNKNOWN` (no signal from any source). Batched to avoid N+1 queries.
- **`ingestion/change_detection.py::detect_lineup_confirmations`** (new,
  `event_type='lineup_confirmed'`) - fires once per (player, match) the first
  time a tracked squad member's lineup is confirmed; HIGH severity if
  confirmed benched (the real actionable "your player got left out" signal),
  MEDIUM if confirmed starting. Wired into `ingestion/fotmob_source.py::
  sync_match` itself (gained an optional `tracked_squad_ids` param, default
  `None` - every pre-existing call site unaffected) rather than duplicated
  per-caller - both `refresh_in_progress_matches` (run-scheduled's ~30min
  cadence) and `fpl live-match-poll`'s ~25s loop get it automatically.
- **`optimization/decision_engine.py::_evaluate_captain`** gained a real, hard
  override: if the locked captain's own `resolve_lineup_state` reads
  `CONFIRMED_BENCHED`/`OUT_UNAVAILABLE`, the verdict is forced to `"change"`
  regardless of the median-xP delta threshold - the projection model may not
  yet reflect a last-minute confirmed exclusion the way this real signal
  already does. Falls back to the best real alternative when the model's own
  `best` option happens to equal the excluded captain.
- **Dashboard**: `_pitch_html_from_xi`/`_player_card` swapped the old
  predicted-only badge for the real 4-state one - `CONFIRMED_STARTING`/
  `PREDICTED_START` stay a small, quiet compact marker (this project's own
  earlier "saturated pill on every card communicates nothing" lesson, not
  repeated here), `CONFIRMED_BENCHED`/`OUT_UNAVAILABLE` keep the existing
  attention-grabbing full pill. `_risk_monitor_html` gained a real
  ACTION-tier row for any locked-squad member confirmed benched, deduped
  against the existing availability-sourced rows by player_id.

### 2. One authoritative GW lifecycle (`models/gw_lifecycle.py`, new)

`compute_gw_lifecycle_state(conn) -> GWLifecycleState` - `PRE_DEADLINE ->
LOCKED -> LIVE -> GW_FINISHED -> NEXT_GW_ANALYSIS -> READY_FOR_NEXT_DEADLINE`,
plus the honest `UNKNOWN` data-integrity fallback above. Pure DERIVED
function, recomputed fresh every call (no in-memory state - a process restart
is automatically correct, nothing to recover). Anchor event resolved via
`events.is_current=1` (FPL's own real "gameweek in its live/settling window"
signal, confirmed live against the real DB), falling back to
`models.fixtures.live_or_reference_event()`. GW_FINISHED vs NEXT_GW_ANALYSIS
vs READY_FOR_NEXT_DEADLINE is resolved via two real `app_meta` markers (
`post_gw_pipeline_started_event`/`post_gw_pipeline_done_event`, not one) -
deliberately two, not one: if the pipeline crashes partway through, "started
but not done" must keep reading as real in-progress work, not silently revert
to looking untouched. Every pipeline step is itself idempotent, so simply
re-running it is always safe.

**`models/fixtures.py::finished_fixture_ids_fast()`** (new) - extracted the
real "fixture finished, fast-source-overridden" query that had been
independently duplicated in `_squad_live_window`/`_player_play_states`
(dashboard.py) into one shared function, now used by both of those AND
`gw_lifecycle.py` - the actual "use it consistently" requirement, satisfied
by de-duplication, not a new parallel implementation. Behavior-preserving
refactor, verified via the existing dashboard-state test suite staying green.

**`_dashboard_state()`** rewired to source from `compute_gw_lifecycle_state`
instead of its own separate 3-way split - same 3 CSS buckets as before
(PRE_DEADLINE/LIVE/POST_MATCH, no new visual redesign), LOCKED gets a small
real header label ("LOCKED - waiting for kickoff") rather than a fourth
bucket. `optimization/locked_squad.py::is_locked()`/`get_locked_squad()`
(already built, Mode A vs B) is left as the actual mode-switch signal - a
real synced squad is ground truth regardless of exact calendar lifecycle
state, a stronger and already-correct signal than deriving mode from time.

### 3-5. Event-driven runtime + post-GW pipeline (`optimization/post_gw_pipeline.py`, new)

`run_post_gw_pipeline(conn, event)` - the deterministic, zero-LLM sequence:
re-syncs match state once more, backfills any FULL_TIME match still missing a
queued qualitative-analysis job (a permanent, automatic version of the manual
backfill done by hand earlier this same day for Arsenal-Coventry), reads the
real locked squad (`get_locked_squad`, bails out honestly with no fabricated
plan if nothing's locked), computes captain/transfer verdicts
(`evaluate_locked_squad`, already-tested) and chip verdicts (cheap
`bench_boost_value`/`triple_captain_value` plus - the one place a full
wildcard/free-hit ILP re-solve is affordable, once per gameweek rather than
every dashboard regen - fresh `wildcard_value`/`freehit_value`), logs a real
`post_gw_plan` decision (and a `chip` decision in the exact shape the existing
Chip Strategy panel already reads, so its "as of Xh ago" refreshes
automatically) and sets the `done` marker.

`maybe_run_post_gw_pipeline(conn)` - the real entry point, a cheap no-op
unless the lifecycle state says there's genuine work left. Wired into both
`run_scheduled` (after match-intelligence refresh/discovery, before the final
dashboard regen) and `live_match_poll_cmd`'s loop (right after a real
FULL_TIME transition tick, so an actively-watching user gets the plan within
~25s of the last match ending, not waiting up to 30min for the next scheduled
tick).

**`fpl post-gw-pipeline`** (new CLI command) - a real, permanent, network-free
entry point into the same `maybe_run_post_gw_pipeline` call, built specifically
to make the critical runtime test possible (see above) but genuinely useful
standalone too (manual/scripted invocation, debugging a stuck pipeline).

**Item 6 (don't rerun the strategic optimizer after every event) was already
true of the existing architecture, verified not assumed**: nothing in
`live_match_poll_cmd`'s tight loop calls a fresh transfer/captain optimizer
solve - it only re-syncs match data and regenerates the dashboard, which reads
`evaluate_locked_squad`'s already-cheap live computation (unchanged by this
session) rather than a heavy re-solve. The new lineup-confirmation detector
only ever writes a `change_events` row; it never forces a recompute - the
dashboard's next natural regen picks up any real change on its own.

**Item 7 (zero-cost AI)**: nothing in this pass calls an LLM. The
qualitative-analysis queue + `.claude/hooks/queue_check.py` SessionStart hook
(already built) remain the only Claude-touches-it path, completely unchanged.

### 9. Post-GW dashboard - Next GW Plan panel

`_next_gw_plan_html()` (new) - reads the real `post_gw_plan` decision the
pipeline logs once per gameweek, renders KEEP/TRANSFER/CAPTAIN/CHIP verdict
rows (REVIEW reserved for an unresolvable/insufficient-data case). Shown in
the existing POST_MATCH panel-promotion slot (GW_FINISHED-family lifecycle
states) - no fourth CSS bucket, reuses the exact panel-promotion mechanism
already built for the LIVE state.

### 10. Testing - real, not just unit-level

New files: `tests/test_gw_lifecycle.py` (12 tests - every state, the 3 direct-
requirement trustworthiness guards, multi-match partial-finish stays LIVE,
restart-recovery via two independent calls agreeing), `tests/test_lineup_state.py`
(8 tests - all 5 states, real priority order, the real pre-kickoff-confirmed-
lineup case), `tests/test_post_gw_pipeline.py` (7 tests - idempotency, honest
bail-out without a locked squad, real decision-detail shape, analysis-job
backfill, the maybe-run gate). Additions to `test_change_detection.py` (3),
`test_optimization_decision_engine.py` (3), `test_dashboard.py`/
`test_dashboard_state.py` (7). 782/782 full suite.

**The actual acceptance test, run for real against a scratch copy of the live
production DB** (not the unit tests alone): copied `data/fpl.db`, marked GW1's
remaining fixtures finished in the copy only, cleared the pipeline markers,
confirmed `source_health` still read healthy (so the real, valid
trustworthiness path was exercised, not a guard-bypassed shortcut), then ran
the real compiled `fpl.exe post-gw-pipeline` via PowerShell against
`$env:FPL_AGENT_DATA_DIR` pointing at the scratch copy - a genuine separate OS
process, no Python function called directly by Claude, no interactive
reasoning involved in producing the result. Real, verified output: lifecycle
state `READY_FOR_NEXT_DEADLINE`, a real `post_gw_plan` decision (captain=keep/
Haaland, transfer=transfer/+7.0xP, real chip values), the scratch
`dashboard.html` genuinely switched to `state-post_match` with the Next GW
Plan panel showing real KEEP/TRANSFER rows - all produced by the subprocess
alone. Re-ran the identical subprocess a second time: clean no-op, exactly one
`post_gw_plan` decision in the DB (no duplication), proving both idempotency
and restart recovery for real, not just in a mocked unit test. Scratch
artifacts deleted afterward, production DB never touched.

**`config.py::DATA_DIR`** gained a real, additive `FPL_AGENT_DATA_DIR` env
override (defaults to today's exact behavior for every existing caller/test)
specifically to make the above subprocess test possible without touching
production data - `CACHE_DIR`/`RAW_DIR`/`DB_PATH` all now derive from it.

## Dashboard overhaul: real bugs, new data modules, visual pass (2026-08-22, continuation session)

Direct, blunt user feedback after using the real live dashboard: several confirmed
real bugs, plus a broad "doesn't look like a real product" complaint referencing
fpl.page as the bar. Went through plan mode (investigated live against the real
dashboard and fpl.page's own browsed structure before planning); user chose
**everything in one pass**, confirmed player-prop odds after a live availability
check, and defined Statistics as season stat leaders.

**Real bugs fixed, each confirmed live before AND after:**
- **Blank/white kit squares** - `_player_card`'s shirt `<img>` had no `onerror`
  fallback; a real load failure (ad-blocker, extension, transient CDN hiccup - the
  URL itself is real and correct, confirmed via a direct `curl`) rendered a blank
  box instead of the existing `.shirt-fallback` styling. Fixed - both elements
  always render now, a failed load reveals the fallback.
- **"Next kickoff: LIVE NOW" - confirmed live to be genuinely wrong.** Arsenal-
  Coventry had finished ~15h earlier, the next real fixture was ~90min away, yet
  the hero strip showed "LIVE NOW" because that one strip item reused
  `_LiveWindow.state` (deliberately stays "live" for the whole GW1 weekend -
  correct for the hero-xp tile's cumulative scoring) instead of the finer,
  already-computed `any_in_progress` field. Fixed - that one strip item only.
- **Optimizer Delta's "Real xP" - a stale-framed pre-match projection once real
  matches had played.** Moved `_compute_my_live_score`'s computation earlier in
  `generate_dashboard_html` (was built after the compare panel, now before) so
  `_compare_panel_html` can show real accrued actual points ("15 GW1 pts") next to
  the honestly-relabeled "Projected xP", same pattern the squad header already
  established. Live-verified: the panel now reads "15 GW1 pts · Projected xP 51.92"
  instead of a bare, stale "Real xP: 51.92".

**Four new panels, all reusing already-built-but-unsurfaced or already-ingested
data - no new modelling:**
- **Price Predictions** - `models/price_forecast.py::classify_price_change()`
  (built Pillar 1a, never wired into the dashboard until now) - real transfer-
  momentum-derived RISE_LIKELY/FALL_LIKELY/STABLE per squad player, explicitly
  labeled uncalibrated.
- **Team Odds** - `fixture_odds_live` (already-ingested, `fpl sync-live-odds`) +
  `models/odds_devig.py` (already-tested pure devig functions) - real win/draw/
  loss + O/U 2.5 probabilities per upcoming fixture, squad-relevant first, honest
  "no live odds yet" when a fixture has no row.
- **Player Odds (anytime goalscorer)** - genuinely new data, **live-verified
  before building**: the-odds-api's per-event endpoint
  (`/v4/sports/soccer_epl/events/{id}/odds?markets=player_goal_scorer_anytime`)
  returned real, current player names/prices (confirmed via a real live call, 1
  credit/event per the real `x-requests-remaining` response header). New
  `ingestion/player_odds_source.py` + `player_odds_live` table (migration 0028) -
  reuses `odds_live_source.py::match_fixture` (team-name resolution) and
  `predicted_lineups_source.py::match_player_in_team` (the already-fixed
  "maximal munch" name matcher) rather than duplicating either. Reports the RAW
  implied probability (1/price), explicitly NOT devigged - a goalscorer market's
  overround can't be removed the same simple way a 2/3-outcome match-result
  market can (no explicit "no goalscorer" residual is quoted), and this project
  doesn't fabricate a devig method it hasn't verified. **Real cost-consciousness,
  live-verified**: a first pass with no date bound matched ~300 not-yet-finished
  fixtures for the squad's ~8 teams (the whole rest of the season); bounded to a
  real 14-day kickoff window (matches what the-odds-api's own events endpoint
  actually returns anyway) plus a per-fixture 4h freshness gate before any
  network call - safe to call on every `run_scheduled` tick without threatening
  the free-tier monthly budget.
- **Statistics (season stat leaders)** - real, live-verified data-source
  correction caught before shipping: `player_season_history` (this project's
  existing historical-seasons table) is ONLY ever populated from a season's
  `history_past` once that season has fully ENDED - checked live, genuinely zero
  rows for the current 2026-27 season. Built against `player_stats_snapshot`
  instead (the real, already-synced CURRENT-season running totals FPL's own API
  reports every regular sync) - the correct source, not assumed.

**Automatic-update requirement (direct user instruction: "make sure every single
thing updates on its own"):**
- `fpl sync-live-odds` was a standalone/manual-only command despite feeding the
  new Team Odds panel - wired into `run_scheduled`'s regular ~30min cycle (cheap,
  one bulk call, real 2 credits per the project's own already-documented cost).
- `sync_player_odds` wired into `run_scheduled` too, safe on every tick because of
  its own internal freshness throttle (most ticks are a real no-op, not a network
  call).
- Price Predictions/Statistics needed no new sync at all - both read data that
  was already part of the regular automatic sync cycle; only the dashboard-
  rendering code was new.

**Visual pass, referenced directly against fpl.page (browsed live before
building), bounded to CSS - no markup/logic restructuring:**
- Base font-size raised via `html { font-size: 18px }` (was unset/16px) - every
  panel/table/list size in this stylesheet is already expressed in rem, so this
  one change scales the whole dashboard proportionally rather than hand-editing
  dozens of rules.
- Pitch/squad cards enlarged (kit art 68px->84px, card min-width 148px->168px,
  proportional bench/mobile-breakpoint scaling) - referenced against fpl.page's
  own denser-but-clean pitch.
- Team Outlook gained a real per-row freshness tag (`predicted_lineup_teams.
  fetched_at`, `_relative_time`) - the underlying churn/formation/news data was
  already real and current, but nothing showed the reader how current, so aging
  pre-deadline copy ("will miss Gameweek 1") read as stale mid-gameweek even
  when it wasn't.
- Chip Strategy rows gained a real, disclosed one-line context sentence derived
  from the already-computed value's own sign/magnitude (negative / <2xP modest /
  >=2xP meaningful) - same real threshold `_decision_center_html`'s own chip card
  already uses, not a new heuristic.
- Live rank promoted from a single hero-strip text line to its own real
  hero-metric stat tile (same shape as Captain/Vice/Squad-value), reading the
  real `estimated_rank` field from the decision's own detail dict (falls back to
  the summary string for a decision logged before that field existed).

**Testing**: new `tests/test_player_odds_source.py` (7 tests - real matching,
real freshness throttle including a proof the network call itself is skipped
when fresh, the real near-term window bound, the no-API-key path), additions to
`test_dashboard.py` (7 - the 4 new panels' real-data and honest-empty-state
cases) and `test_dashboard_state.py` (5 - `any_in_progress` vs `state`, the
onerror fallback, the compare-panel actual-points fix both with and without a
live payload). One real regression caught and fixed by the existing suite (not
missed): `test_hero_shows_the_last_logged_live_rank` broke on the live-rank tile
rewrite (a real decision logged without the newer `estimated_rank` detail key,
plus a label-casing mismatch) - fixed with a real fallback to the decision's own
summary string rather than a bare "?", and matching the tile label's exact
existing casing.

## Fixture Projections replaces bookmaker odds + real "kit on grass" pitch redesign (2026-08-22, same day, continued)

Direct, blunt follow-up to the dashboard-overhaul pass above: "no full automatic
fixtures similar to fpl.page... i dont want book odds, i want projected goals
score + clean sheet %... squad thing, the background is white, thats not what i
want... similar to how teams look in official fpl site or how fpl.page does it."
Investigated fpl.page's own real DOM directly (computed styles, not guessed) before
building either fix.

**Fixture Projections replaces the "Team Odds" panel entirely.** Live-verified
against fpl.page's own real "GAMEWEEK PROJECTIONS" module: a real TEAM x GW numeric
grid (projected goals, a separate clean-sheet-% table), never an odds/probability
framing. `_team_odds_html`/its CSS/tests deleted outright (not left as dead code);
new `_fixture_projections_html` reuses the EXACT SAME real numbers the Fixture
Ticker's own hover tooltip already computes (`expected_points.py::_fixture_goals_for`,
`models/blend.py::clean_sheet_probability`, `_cached_fixture_goals_for`'s existing
per-fixture memoization) - two real tables (Projected Goals, Clean Sheet %), all 20
teams, squad rows highlighted, 5-GW + Total/Avg columns, sorted strongest-first -
matching fpl.page's structure with this project's own already-tested data, not a
new model. Real bookmaker odds (`fixture_odds_live`, `fpl sync-live-odds`) stay
wired into `run_scheduled` and the live xP model unchanged - only the odds-framed
DASHBOARD PANEL is gone, not the underlying model input (removing that would
degrade real prediction accuracy for no reason related to the actual complaint).

**Pitch redesign - real root cause found, not guessed.** Inspected fpl.page's own
squad view via direct DOM/computed-style queries (screenshots aren't available in
this environment): their real pitch is a PNG pitch graphic with real per-team kit
renders placed directly on the grass and a small dark name/price pill underneath -
no white card anywhere. This project's own `.pitch` already draws a real green
striped pitch with markings (unchanged, was never the problem) - the actual bug was
`.player-card`'s own white gradient background, putting every player inside a boxed
white card floating on top of the green pitch instead of blending onto it.
- `.player-card` background set to fully transparent, box-shadow/border-top
  removed - it's now purely a positioning container for the kit image + armband/
  bench-order badges.
- New `.player-info` - the one real "card-shaped" element left, a small dark
  semi-transparent pill (`rgba(10,12,16,0.82)`, backdrop-blur) sitting directly
  under the kit, holding name/price/points - matches fpl.page's own real name-pill-
  under-the-shirt pattern. Kept the existing per-position accent-color coding as
  the pill's own top border (was the card's border-top) rather than dropping it.
  All player text recolored from the old dark-on-white palette (#14161a body,
  #146c3a green accents) to a light-on-dark one (white body text, #4ade80 green,
  rgba(255,255,255,*) muted tiers) since it now sits on a dark pill over green
  grass, not a white box.
- `_player_card`'s own HTML gained the `.player-info` wrapper div around name/
  meta/points/lineup-badge (previously flat siblings of the shirt) - the captain's
  gold glow moved from `.player-card.is-captain` (the whole card, no longer has a
  visible boundary) to `.player-card.is-captain .player-info` (the pill itself, the
  actual visible element now).
- Bench-row and the 480px mobile breakpoint's own `.player-card`/`.player-photo-
  wrap`/`.player-shirt`/`.player-name` overrides updated to match (padding moved
  off `.player-card` onto `.player-info`, smaller min-widths since there's no card
  chrome consuming space anymore).
- Live-verified via real computed-style checks (not assumed from the CSS source
  alone): `.player-card` background reads `rgba(0, 0, 0, 0)`, `.player-info` reads
  the real dark pill color, `.pitch` still carries its real green striped
  background-image - confirms the fix landed exactly as designed, not just that the
  CSS parses.

**Testing**: `test_team_odds_*` (2 tests) deleted with the function; 2 new
`test_fixture_projections_*` tests added (real grid rendering, real squad-team
highlighting). 801/801 full suite (2 deleted odds tests replaced 1:1 by 2 real
projections tests - a wash, not a coverage loss).

## Match Intelligence panel broadened from squad-only to all fixtures (2026-08-22, continuation session)

User asked twice, live, during an actual real GW1 gameweek in progress: "why is match
intelligence not running when the game is already going on... why are all the full
fixtures not displayed, not just pertaining to the players in my team." Checked with
real evidence before answering either way, per this project's own standing discipline.

- **Match intelligence WAS genuinely running - confirmed live, not assumed.** Fixture 4
  (Hull City v Man Utd, real kickoff 2026-08-22T11:30:00Z) showed `status='LIVE'`,
  `retrieved_at` moving from `11:47:22` to `11:51:54` while this was being checked (a
  real new goal event, Semi Ajayi 17', landed in that window) - `FPLAgentLivePoll`
  confirmed `State=Running` via `Get-ScheduledTask`. The on-disk `dashboard.html` (last
  written `11:49:39`, ~2min after the live sync) already showed real per-minute stats
  for all 5 in-play locked-squad players (Calafiori/Tzolis/Mbeumo/Maguire/B.Fernandes)
  and a real live match feed. If nothing appeared to update, the most likely real cause
  is a browser tab left open from before the data landed - the page's own meta-refresh
  should pick it up, a reload would too.
- **The second complaint was real and structural, not a bug**: `_match_intelligence_html`
  (`monitoring/dashboard.py`) filtered its `match_intelligence` query to
  `WHERE home_team_id IN (squad's own teams) OR away_team_id IN (...)` by original
  design intent (its own prior docstring: "shown only when at least one match_intelligence
  row involves a squad team"). With the user's current 15-man squad spanning 11 real
  clubs, most of GW1 already showed - only Everton v Crystal Palace and Nott'm Forest v
  Leeds were excluded, since no locked-squad player is on either team. Since the user
  asked for ALL fixtures twice, this was changed rather than just explained: the query
  is now unconditional (every tracked `match_intelligence` row, `LIMIT 20`, still
  status-then-kickoff ordered), and squad relevance is now a `YOUR SQUAD` badge
  (`.squad-badge` CSS, same "highlight, don't hide" pattern the Fixture Ticker already
  uses) rather than a filter. The compact PRE_MATCH row and the full LIVE/HALFTIME card
  both carry the badge; the "Your Players" sub-section inside a live card is only
  rendered when the match is genuinely squad-relevant (an honest empty
  "No locked-squad players in this match" line would otherwise render for every
  non-squad live match, which is real but pure noise).
- **Live-verified against the real dashboard, not just tests**: regenerated `fpl
  dashboard` - all 6 real GW1 fixtures now render (Everton v Crystal Palace and
  Nott'm Forest v Leeds appear for the first time, correctly unbadged), the 4
  squad-relevant ones (Arsenal FULL_TIME, Hull-Man Utd LIVE, Ipswich-Sunderland and
  Brentford-Spurs pre-match) correctly carry `YOUR SQUAD`.
- 1 test rewritten (`test_match_intelligence_panel_shows_all_matches_even_without_a_squad`
  replaces the old squad-required empty-state assertion, which was itself the behavior
  being removed). 801/801 full suite (net wash: one old test replaced by one new test,
  no coverage lost).

## Skill/subagent guidance

Don't invoke multiple subagents for a simple question (section 4.4/100) - most of
what these skills do is "run one CLI command, interpret the output," which the main
thread should just do directly. Reach for a subagent specifically when the task
needs the kind of extended, isolated reasoning pass described in its own file
(a full decision trace, a red-team challenge) - not as a default wrapper for
routine command output.

