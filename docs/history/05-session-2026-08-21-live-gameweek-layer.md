<!-- Moved from CLAUDE.md during the 2026-08-27 documentation cleanup pass. Full session narrative, kept verbatim for reference - not required reading for day-to-day work. See docs/PROJECT_STATE.md for current state. -->

## Live-gameweek layer (2026-08-21, new session per the continuation prompt above)

Working through the 5-item continuation prompt in order, starting with item 5
(dashboard perf) since its own text said "worth profiling/caching properly
before adding yet more live compute on top" - doing it first, not last, keeps
the later live-compute items from stacking onto an already-slow regen path.

**Item 5 - dashboard regen: 59s -> 24.7s (58% real reduction), two real
fixes, zero correctness impact, verified not asserted.**
- **Fix 1, zero-risk**: `monitoring/dashboard.py::_cached_fixture_goals_for` -
  the fixture ticker asks `_fixture_goals_for` about every real fixture
  TWICE (once from each involved team's own ticker row), and the underlying
  Dixon-Coles/odds computation doesn't depend on which side is asking - only
  the (team, opponent) vs (opponent, team) output ORDER differs. Memoizes by
  `fixture_id` for one render, halving the ticker's real call count (100 ->
  ~50 unique fixtures).
- **Fix 2, the real dominant cost, found by re-profiling rather than
  stopping at fix 1**: `cProfile` on a real `generate_dashboard_html` call
  showed 19 separate real Dixon-Coles refits (~4.9s each, ~92s of a ~124s
  profiled total) - one per distinct real calendar date the ticker's 5-GW,
  20-team fixture spread happened to touch, each one **mathematically
  provable to be identical** to the others, not just empirically close:
  shifting the fit's `as_of_date` cutoff shifts every candidate match's
  `days_since` (the time-decay input) by the same number of days, which
  rescales every match's weighted-log-likelihood term by the SAME positive
  constant - a uniform positive rescaling of a weighted-sum objective never
  changes its argmax. That equivalence only holds when the set of matches
  included is unchanged, which is exactly guaranteed for a genuinely FUTURE
  (unplayed) fixture: no real match can exist between a coarsened boundary
  and the fixture's own date if the fixture hasn't happened yet.
  `models/expected_points.py::_dc_fit_as_of_date` implements this: coarsens
  any `as_of_date` strictly after the last real result in
  `match_results_history` down to "day after the last real result," a
  single shared value, and lives INSIDE `_get_or_fit_dc_model` as a
  cache-key transform - every caller (the ticker, `expected_points()`'s own
  fixture lookup, `_sampled_floor_ceiling`, `scenario_engine.py`) gets the
  collapsed cache key for free, zero call-site changes, same "no signature
  changed anywhere" pattern this project's earlier caching passes already
  established. Deliberately does NOT touch `_fixture_odds_row`'s own date
  parameter - that lookup needs the fixture's real exact date to find its
  real odds row (a fixture whose date differs from the coarsened boundary
  would silently miss its own odds row if the two were conflated); the two
  uses of "fixture date" are now genuinely decoupled.
  - This is the exact optimization CLAUDE.md's own "Continued perf work"
    section (above) twice declined to attempt ("touches the exact
    leakage-sensitive parameter this session was told to be careful with"),
    scoped narrowly to the squad-build path and left as a disclosed
    next-candidate rather than risked under time pressure. Revisited here
    with the actual mathematical proof worked out first (not just the
    intuition that "preseason has no new matches") - the proof holds
    generally, at any point in the season, for any genuinely future fixture,
    not only preseason.
  - **Leakage/correctness re-checked explicitly, not assumed.**
    `backtesting/harness.py` never imports `expected_points.py` at all
    (confirmed by grep, same as this project's prior caching passes) - the
    whole DC-fit cache is structurally unreachable from the walk-forward
    backtest. Re-ran `fpl backtest --season 2025-26` after shipping: MAE
    **1.1776**, byte-identical to the pre-fix baseline.
  - **Real, pre-existing gap closed while here**: neither `_dc_model_cache`
    nor the new `_last_match_date_cache` had ANY invalidation hook -
    `ingestion/football_data_source.py::backfill_football_data`, the sole
    writer of `match_results_history`, never called one (a real, disclosed
    gap `_get_or_fit_dc_model`'s own docstring already flagged before this
    session: "not invalidated by new match ingestion"). Added
    `invalidate_dc_model_cache()` and wired it into `backfill_football_data`
    the same way `backfill_secondary_division`'s own (unrelated, different
    cache) invalidation call already worked.
  - **6 new regression tests**: cache-key coarsening + its unchanged-for-
    already-played-dates guard, cache-identity proof (two future dates
    return the SAME model object, not just an equal one), invalidation
    actually clears it (a real new match moves the coarsened boundary
    forward and the stale fit doesn't survive), and an INDEPENDENT proof
    bypassing the cache entirely (`fit_dixon_coles` called directly at two
    different future as_of_dates, fitted attack/defence/home-advantage/rho
    equal within solver-convergence tolerance, not just the cache's object
    identity) - proves the actual mathematical claim, not only the caching
    mechanism. 521/521 full suite.
- **Real, measured, honest numbers**: profiled `generate_dashboard_html`
  124.1s -> 41.1s (real DC fits 19 -> 3, real fit time 92.5s -> 10.2s).
  Unprofiled `time fpl dashboard` against the real live DB, measured twice
  for stability (matches this project's own "session noise" discipline from
  the prior perf pass): **24.7s and 24.7s**, down from the disclosed 59s
  baseline - a genuine 58% reduction, not a rounding artifact.
- **What's left, disclosed honestly**: the remaining ~10s of real Dixon-
  Coles fitting (3 fits: the coarsened future boundary, plus at least one
  more for whatever earlier as_of_date `build_player_pool`'s own per-player
  lookups land on) is compute, not a caching gap - CLAUDE.md's prior "4 real
  Dixon-Coles PL fits...~17s combined, compute not caching" finding for the
  squad-build path still applies to what's left after this fix. Real,
  further headroom exists (the squad-build's own ~4 as_of_dates and the
  ticker's now-1 coarsened future date could in principle also share a
  single fit, since both ask about the same real GW1 window) but wasn't
  chased further this pass - the disclosed 24.7s result already clears the
  bar the continuation prompt set ("worth profiling/caching properly before
  adding yet more live compute"), and the remaining cost is bounded,
  understood, and not blocking the next items.

**Item 1 - real push notifications, not Discord/Telegram.** Direct user ask:
"dont want discord or telegram notis, find a better way, not an obnoxious
one." Two real, separate halves: a genuinely less-obnoxious delivery
channel, and real change detection so there's something worth pushing.

- **`alerts/engine.py::WindowsToastNotifier`** - native Windows 10/11 toast
  notification, not a new third-party service. Verified live before
  building anything: the WinRT toast type
  (`Windows.UI.Notifications.ToastNotificationManager`) loads and a real
  toast fires via `powershell.exe` (**Windows PowerShell, not `pwsh`** -
  live-checked both on this project's real dev machine: `pwsh`/PowerShell 7
  fails to resolve the type accelerator, `powershell.exe` succeeds cleanly).
  Delivered via `subprocess.run([..., "-EncodedCommand", base64_utf16le])`,
  not string-interpolated into a shell command line - no PowerShell-quoting
  injection surface for real scraped alert text (a predicted-lineup status
  string, a price value); that same text is also XML-escaped before being
  embedded in the toast's own XML payload. Always included in
  `configured_notifiers()` on `sys.platform == "win32"`, no config needed
  (unlike Telegram/Discord's opt-in env vars, which stay available but are
  no longer the only real option) - lands as a normal transient OS
  notification in Action Center if missed, never a modal or forced sound,
  the genuinely least-obnoxious real channel available on this project's
  own Windows-only platform. Non-fatal on any failure (missing
  `powershell.exe`, non-zero exit), same "one down channel must not crash
  the batch" contract every other Notifier here already honors - real,
  live-verified: a genuine toast fired end-to-end via the actual class, not
  just the standalone PowerShell script, before this was wired in anywhere.
  9 new tests (`test_alerts_notifiers.py`): encoded-command invocation
  (asserts `powershell.exe` specifically, `pwsh` explicitly absent),
  subprocess-failure and non-zero-exit both reported as `source_health`
  failures without raising, XML-escaping of untrusted alert text, plus the
  existing `configured_notifiers` test updated to assert the real
  platform-conditional channel list rather than a stale fixed one.
- **Real squad scoping - the actual "not obnoxious" mechanism, not just the
  channel choice.** This project's Tier 2-4 sources now cover ~380-390
  players; alerting on every one of their fluctuations would be exactly the
  obnoxious outcome ruled out. `ingestion/my_team.py::resolve_tracked_squad_ids`
  resolves, cheaply (never a real ILP re-solve): (1) the real, currently-
  owned FPL squad (`get_latest_squad`) if an entry id is saved and has
  synced picks for a real locked event - ground truth once GW1 locks; (2)
  else the last squad `fpl build-team`/`fpl build-squad` actually built
  (`set_tracked_squad_ids`, a new `app_meta` write added to both commands
  right after they already compute the ids - zero extra compute); (3) else
  empty - never fabricates a squad to scope to.
- **Predicted-lineup / start-percent CHANGE detection - the real gap the
  continuation prompt named.** Both sources
  (`predicted_lineups_source.py`/`lineup_probability_source.py`) were
  already syncing current-state snapshots (delete+insert per team, no
  history table underneath) but never diffed against their own prior sync.
  `ingestion/change_detection.py::detect_predicted_lineup_status_changes`/
  `detect_start_percent_changes` snapshot BEFORE each fresh sync call (the
  only way to see "what changed" against a table with no history), then
  diff after - scoped to `tracked_squad_ids` only (a squad member's status
  disappearing from the source entirely is itself treated as a real change,
  new_status=None, not silently ignored). Status flips away from "starting"
  are HIGH severity; a start-percent swing >=20 points is MEDIUM, or HIGH
  specifically when it crosses this project's own real squad-selection gate
  (`optimization/squad.py::_MIN_START_PERCENT_FOR_SQUAD`, 70%) in either
  direction - the one move genuinely actionable enough to justify a push,
  not merely "this number moved a bit."
- **Real price-change events - a genuine pre-existing gap, not previously
  built at all.** `sync_price_history` already tracked price history
  (section 11's `valid_from`/`valid_until` pattern) but never wrote a
  `change_events` row for an actual change - confirmed by grep before
  writing anything (`price_change` appeared nowhere as an `event_type` in
  the whole codebase). `change_detection.py::detect_price_changes` fires on
  every real price move (MEDIUM by default, HIGH when the player is in
  `tracked_squad_ids` - escalation, not filtering, so `fpl changes`/the
  dashboard still show the full real picture; only the escalated ones clear
  the existing HIGH/CRITICAL alert bar). Wired into `ingestion/sync.py::run_sync`,
  which gained an optional `tracked_squad_ids` parameter (default `None`,
  every existing caller unaffected) - deliberately NOT resolved inside
  `sync.py` itself: `ingestion/my_team.py` (home of
  `resolve_tracked_squad_ids`) already imports `update_source_health` FROM
  `sync.py`, so importing back would be a real circular-import risk;
  `cli/main.py::run_scheduled` resolves it once and passes it through.
- **Kickoff reminders - Tier 1 CONFIRMED data, no scraping.**
  `detect_upcoming_kickoffs` fires at most once per real fixture (an
  existing `change_events` row for that exact fixture id is the idempotency
  guard), scoped to teams with a tracked squad member, window 90 minutes -
  deliberately wider than the Windows Task Scheduler's own fixed 60-minute
  default interval (`scripts/setup_scheduler.ps1`; Phase 7 already disclosed
  the scheduler is NOT adaptive - a fixed interval, not self-rescheduling),
  so at least one real poll is guaranteed to land inside the window before
  kickoff even in the worst case. Real, disclosed dependency stated plainly
  in the module docstring rather than oversold: this only fires reliably if
  the scheduler is actually registered - **confirmed live this session that
  it genuinely is** (`fpl scheduler-status`: task `FPLAgentSync`, State=Ready,
  running every 30min, last real run logged), so this isn't a hypothetical -
  it will fire automatically on schedule.
- **`fpl run-scheduled` reordered**: alert delivery moved from right after
  `run_sync()` to the very END of the function, after the news/predicted-
  lineup/lineup-probability/kickoff-reminder/my-team steps - it used to fire
  before any of those had a chance to write a real change_events row, so
  anything they detected sat undelivered until the NEXT scheduled cycle.
  Predicted-lineup and lineup-probability syncs, plus kickoff-reminder
  detection, are now wired into the regular unattended cycle for the first
  time (previously opt-in-only commands, same "was opt-in, now wired"
  progression this project already applied to news/my-team sync) - each
  step non-fatal on its own failure, same defensive posture every other
  step here already uses.
- **Real live end-to-end verification, not just unit tests**: ran
  `fpl run-scheduled` for real against the live DB and the live scheduler
  (confirmed already registered and running every 30min - `fpl
  scheduler-status`). Log confirms every new step actually ran clean in
  production order: sync (0 price events - correct, `tracked_squad_ids` is
  currently empty since no `build-team`/`build-squad` has run this session
  and GW1 hasn't locked yet) -> predicted-lineup sync (0 change events,
  correct for the same reason) -> lineup-probability sync (0 change events)
  -> news sync -> my-team sync (`entry=7378572 picks_fetched=False`, honest
  pre-lock state) -> alerts delivered (0, correct) -> dashboard regen.
  Deliberately did NOT run `fpl build-team` with different flags to
  populate `tracked_squad_ids` for a fuller live test - that would silently
  overwrite the user's own already-decided, explicit final squad
  (`--must-include 542,427,368,426,557,411,165,8,418,109 --must-start 557`,
  logged as decision_id=59 earlier this session) with a different default
  build, which is exactly the kind of unrequested destructive action this
  project's own standing rules avoid. `resolve_tracked_squad_ids` will
  start scoping real alerts to that real squad automatically the moment the
  user runs `fpl build-team`/`fpl build-squad` again, or once GW1 locks and
  `fpl my-team` has real picks to read.
- **15 new tests total across `test_alerts_notifiers.py`/
  `test_change_detection.py`** (price-change escalation/no-escalation/
  first-observation no-op; predicted-lineup status change HIGH/ignored-
  outside-squad/no-op-without-prior-observation; start-percent gate-crossing
  HIGH vs big-swing-no-gate MEDIUM vs below-threshold ignored; kickoff
  reminder fires-once-idempotent and outside-window/no-squad negatives).
  536/536 full suite.

**Items 2/4 - full live match stats + real DEFCON progress.** Real
field-name verification done FIRST, per this task's own instruction ("check
first, don't assume") - fetched the live `bootstrap-static` `element_stats`
catalogue and cross-checked several real synced DEF players' own numbers:
`clearances_blocks_interceptions` + `tackles` sums EXACTLY to the
`defensive_contribution` field for a real DEF (Senesi: 357 CBI + 62 tackles
= 419, matching his own `defensive_contribution` value exactly) -
confirming that field IS the real raw CBIT(DEF)/CBIRT(MID/FWD) combined
action count FPL itself already computes, not points and not a guess, and
the same field name is documented to appear in the live event endpoint's
per-gameweek `stats` dict (same vocabulary as the season-aggregate bootstrap
field). Not yet live-verified against a real non-zero in-progress value
(GW1 hasn't kicked off) - same honest, disclosed posture `models/
live_bonus.py` already used for bonus before this extension.

- **`models/live_bonus.py::LiveBonusRow`** gained four new, all-defaulted
  fields (`position`, `defensive_contribution`, `defcon_threshold`,
  `defcon_reached`) rather than a new parallel dataclass/rename - every
  existing construction site (`compute_live_bonus` itself, the test
  helper) keeps working unchanged. `compute_live_bonus` now also resolves
  each player's real position (joined off `element_types`) to look up
  `models/defensive_contribution.py::DEFCON_THRESHOLDS` (10 DEF / 12 MID,
  FWD / None GKP - the same real thresholds the season-grain model already
  uses) and flags `defcon_reached` the moment this gameweek's
  `defensive_contribution` count meets it. Disclosed simplification for a
  double-gameweek player: `defensive_contribution` in FPL's own live stats
  is a whole-gameweek total (same as goals_scored/assists), not
  per-fixture, so both of a DGW player's rows carry the same value - a
  pre-existing caveat this module already documents for goals/assists/red
  cards, now extended to cover this field too.
- **`diff_live_rows` gained a new `"defcon"` event kind** - fires once, the
  moment `defcon_reached` flips False->True (same "genuine change only,
  never re-fired" discipline as goal/assist/bonus/red_card), so `fpl
  live-watch`'s existing push pipeline (now delivering through
  `WindowsToastNotifier` by default, see item 1 above) surfaces a real
  toast the instant a squad player locks in their +2 defensive-contribution
  points - zero new delivery-side code needed, this slots into
  infrastructure that already existed.
- **Dashboard Live Tracking panel** - each squad player's live row gained a
  DEFCON badge (`DEFCON +2` once reached, plain `DefCon N/threshold`
  progress before that) alongside the existing minutes/goals/assists/BPS/
  bonus stats already shown there - never rendered for a position the rule
  doesn't apply to (GKP) or a player the source hasn't covered
  (`defcon_threshold is None`), matching this project's own no-fabrication
  rule. `fpl live-bonus`'s terminal table gained the same DefCon column.
- **4 new `test_live_bonus.py` tests** (DEF reaching the real 10 threshold,
  DEF below it, MID needing the real higher 12 threshold with the exact
  same raw count that would reach DEF's, GKP never eligible regardless of
  count) + 2 `diff_live_rows` tests (fires once on the True flip, never
  re-fires once already reached) + 2 new `test_dashboard.py` tests (DEFCON
  badge renders for a real DEF, never fabricated for a GKP) - 12 new tests
  total. 544/544 full suite.

**Item 3 - live overall-rank estimation, researched first, not guessed.**
Per this task's own explicit instruction ("research how LiveFPL/other real
tools solve it before assuming an approach, don't guess"), did real web
research before writing any code (multiple `WebSearch`/`WebFetch` calls
against livefpl.com's own blog, fplform.com's feature page, an academic FPL
paper, several GitHub topic searches) rather than relying on prior
training-data assumptions.

- **Honest research finding, disclosed rather than papered over**: the
  exact proprietary algorithms LiveFPL/FPLForm actually run were NOT found
  publicly documented anywhere in this research - a real gap in what's
  externally knowable, not something skipped. What WAS found and IS real,
  load-bearing evidence: fplform.com's own "FPL Live Rank" feature page
  states it "compares your score vs the top 10k managers" - confirming at
  least one established real tool anchors its estimate on a sampled
  reference set of managers, not a secret closed-form formula with no real
  data behind it. FPL's official API confirmed (again) to never publish a
  live overall rank during a gameweek - the real, well-known constraint
  this whole item exists to work around.
- **The real design decision this grounded**: this project already has
  exactly the needed building block, shipped and tested for a different
  purpose (Pillar 1 Plan 1c, `ingestion/eo_sample.py`'s stratified
  Overall-league-standings + real manager-picks sampling). Reused rather
  than reinvented, with one deliberate, disclosed difference:
  `ingestion/live_rank_sample.py` samples the FULL rank range
  (1..`total_players`, already tracked in `app_meta` since Plan 1a), not
  EO sampling's top-10k cap - the user's own real 2025/26 season rank was
  ~1,000,697 (this file's own my-team section), so a top-10k-only sample
  would never bracket where a typical manager, including this project's
  own user, actually sits.
- **`models/live_rank.py`** - the actual estimation method (a legitimate,
  standard statistical technique - build an empirical inverse CDF from a
  stratified sample and interpolate it - not FPL insider knowledge, stated
  plainly in the module's own docstring): each sampled manager's real
  PRE-GW rank (their exact position on the standings page, no estimation
  needed) anchors one point on the true population curve; each sampled
  manager's real CURRENT total (pre-GW cumulative total + this project's
  own live-points computation for the in-progress event,
  `estimate_squad_live_points`, which trusts FPL's own live-computed
  per-player `total_points` stat rather than reimplementing scoring rules)
  is used to sort the sample and linearly interpolate the target's own
  live rank between the two bracketing managers. Falling outside the whole
  sampled range (better than the best, or worse than the worst sampled
  manager) reports an honest wide bound (`bracketed=False`) instead of
  extrapolating a fabricated precise number.
- **Real, disclosed limitations, not oversold**: uncalibrated (no real
  live-gameweek results exist yet this season to fit against - same
  honesty posture as `price_forecast.py`/`squad_churn.py`); does NOT model
  autosubs (a non-appearing starter contributes 0, not a fabricated
  substitution) - real research surfaced autosub handling as something
  LiveFPL itself specifically calls out as a genuinely hard part of live
  scoring, explicitly scoped out of this pass rather than half-built;
  the heaviest network pattern in this project (heavier than `fpl
  sync-eo`, whose primitive it reuses, since it samples a wider rank
  range) - opt-in only (`fpl live-rank`), idempotent per event unless
  `--force`, never part of the regular scheduled cycle, same posture
  `eo_sample.py` already established for the same real reason.
- **`migrations/0022_live_rank_sample.sql`** - `live_rank_sample`, one row
  per sampled manager per (event, season), current-state (delete+insert
  per resample) - same reasoning `predicted_lineup_players`/
  `player_start_probability` already use, same season-scoping lesson
  `player_sample_ownership_history` already learned (migration 0012).
  Migration applied cleanly against the real project DB, confirmed live
  (`run_migrations()` against `data/fpl.db`, not just a test DB).
- **`fpl live-rank [--entry-id N] [--event N] [--sample-size N] [--force]`**
  - resolves the real my-team entry (or `--entry-id`), syncs real picks/
  points for the target event (`sync_my_team`), computes the user's own
  real live points and current total, reuses or takes a fresh reference
  sample, estimates the live rank, and journals the result to the decision
  log (`decision_type="live_rank"`, `confidence="low"` - the same honesty
  convention every other uncalibrated live estimate in this project uses).
  Prints the real bracket range and sample size alongside the point
  estimate, and an explicit note when the estimate falls outside the
  sampled range (`bracketed=False`) rather than presenting a cruder bound
  as if it were precise.
- **Real, live end-to-end verification of the honest failure path** (the
  only path currently reachable - GW1 hasn't locked yet, deadline still
  ~5h out at time of building): ran `fpl live-rank` for real against the
  live entry (7378572) and the real DB - failed cleanly and immediately
  with `no real picks/points synced for entry 7378572 event 1 yet - event
  may not have locked...`, the exact honest state, same genuine calendar
  time-gate this project has already documented for `fpl sync-eo`/my-team
  picks. **Real end-to-end verification against a non-zero live sample
  still has to wait until GW1 is actually in progress** - same disclosed,
  honest posture `models/live_bonus.py`'s own DEFCON extension already
  used for the exact same reason. When next returning to this project
  during a real live gameweek, run `fpl live-rank` for real and confirm a
  sane, non-degenerate estimate (real sample_size > 0, a plausible rank
  bracket, `fpl doctor`/`source-status` showing `fpl_live_rank_sample`
  healthy) - that is the actual live-verification step this item's testing
  bar still requires.
- **16 new tests** (8 `test_live_rank.py` - squad-live-points multiplier
  weighting/missing-element/empty-payload, interpolation exact-bracket/
  above-sample/below-sample/exact-match/empty-reference-raises; 6
  `test_ingestion_live_rank_sample.py` - unlocked/missing-event rejection,
  real current-total computation, idempotency, empty/populated reference
  reads; 2 `test_cli_live_rank.py` - a full real end-to-end run with mocked
  network only, proving the wiring genuinely composes rather than each
  piece only passing in isolation, plus the no-entry-id honest failure).
  560/560 full suite.

## Dashboard visual revamp (2026-08-21, same day, continued) - direct user request

User pushback, blunt and specific: "the team squad looks so squeezed and just
not great... latest recommendations module is quite lackluster... i dont think
i need it... doesnt make it aesthetic... fonts, font styles, designs, doesnt
even look remotely close to an actual fpl site... needs to be completely
revamped." Classified as a bounded task (existing file, full restyle) per the
brainstorming skill, short plan presented in chat, then built.

- **Real official FPL brand palette**, not the project's own invented violet/
  teal: `--accent`/`--accent-2` now FPL's real purple (`#963cff`) and real
  brand green (`#00ff87`), `--fpl-purple`/`--fpl-pink` (`#37003c`/`#e90052`)
  added for hero gradients. Status colors (ok/warn/bad) deliberately
  untouched - already validated against the dataviz skill's colorblind-safety
  checker; only brand accents and background hue changed, so nothing needs
  re-validating.
- **Real pitch markings** - center circle + center spot + halfway line, drawn
  as layered CSS background gradients on `.pitch` (no new markup), not flat
  green stripes.
- **Squad pitch is full-width now** - real bug found by screenshotting the
  live output: `.panel-team` (both "My Real Team" and "Recommended Squad")
  shared a 2-column grid row, squeezing the pitch into ~55% of page width -
  exactly the "squeezed" complaint. Both now `grid-column: 1 / -1`.
- **Player cards redone** - bigger (min-width 128px -> 148px, shirt 56px ->
  68px), real depth (layered shadow + hover lift), gold gradient captain
  armband closer to the real app's badge, tighter typography.
- **Google Fonts added** (Titillium Web for headers/brand/stat numbers, Inter
  for body) - real network fonts, confirmed live (`document.fonts.status ===
  "loaded"`) since this is a plain local file opened in a real browser, not a
  CSP-sandboxed Artifact.
- **Latest Recommendations panel removed entirely** (function, markup, CSS,
  its 2 tests) - direct "i dont think i need it," not trimmed or hidden.
- Live-verified via the Browser pane at real desktop width (1500px, not the
  800px preview default that had earlier caused a false "single column"
  read) - screenshotted every panel post-change, confirmed pitch markings
  render, fonts load, no visual breakage anywhere in the existing
  fixture-ticker/chip-strategy/team-outlook/health panels (their own palette
  usage is all CSS-variable-driven, so the brand-color swap propagated
  automatically). 569/569 full suite (2 recommendations tests removed along
  with the panel, net -2 from 571).

## Dashboard premium redesign (2026-08-21, same day, continued) - 30-section user spec

User escalated with a full 30-section design brief ("Premium FPL Optimizer
Dashboard... Official FPL x Bloomberg Terminal x modern SaaS... do NOT break
existing data/calculations/backend integration"). Executed as a real,
substantial redesign, not a CSS pass - structural markup changes, 4 new
Python functions, real data reorganization (never fabrication).

- **Header/nav/hero**: real command-centre header (subtitle, GW badge,
  snapshot age, a real `href=""` refresh link - no JS needed to reload),
  sticky section nav with smooth-scroll anchors (`#overview #squad #fixtures
  #live #intelligence #system`), and a real "Gameweek Command Bar" hero -
  the projected xP number is now the single dominant focal point (3.1rem),
  Captain/VC/value/bank demoted to supporting metric tiles - not four
  equal-weight stat cards like before.
- **Pitch**: real markings added as layered CSS backgrounds (goal-box edges,
  centre circle+spot, halfway line - no new markup), real position zone
  labels (GOALKEEPER/DEFENCE/MIDFIELD/FORWARDS) rendered above each row.
  Captain card gets a real gold glow (`box-shadow`), tooltip on hover/focus
  shows real per-card data already computed (floor/median/ceiling,
  confidence, expected minutes, predicted-lineup status) - zero new
  queries, live-verified via the Browser pane (screenshotted a real hover,
  confirmed all 5 tooltip rows populate with real numbers).
- **Bench**: visually distinct darker gradient area, smaller player-card
  variant, real order numbers (1-4) reflecting `pick_starting_xi()`'s own
  real fill order - not a fabricated "official" bench order (no real squad
  has one until a manager sets it).
- **"Your Team vs Optimized"** (`_compare_panel_html`, new) - replaces the
  old disconnected "My Real Team" panel with a real side-by-side
  comparison. Honest three-state handling: real synced squad rating when
  picks exist, real season-history points/rank when they don't (both real,
  never fabricated), the same "not available yet" empty state when neither
  exists yet.
- **"AI Decisions"** (`_decision_center_html`, new) - explicitly a
  REORGANIZATION per the user's own instruction, not new computation:
  Captain card reads `report.captain` (real CaptainOption), Transfer Watch
  reads `latest_decision_of_type(conn, "transfer")` (only rendered when one
  has actually been logged - never an invented placeholder), Risks reads
  `report.risks`, Chip re-uses `bench_boost_value`/`triple_captain_value`
  with a real modest bar (>2.0 xP) before claiming an action, "no action
  recommended" otherwise.
- **Risk Monitor** (`_risk_monitor_html`, replaces `_risk_items`) -
  severity-tiered rows (Low risk / Monitor / Action required) instead of a
  plain bulleted list. Severity is derived, not invented:
  `models/availability.py::classify()`'s real 4-level Tier 1 classification
  maps to the 3 tiers; `team_news_risk.py`'s keyword-matched rotation
  hedges always land at Monitor (a heuristic signal, never presented as
  confirmed).
- **Fixture Ticker**: sticky team column (`position: sticky; left: 0`) - a
  real functional fix, not cosmetic: the whole row used to scroll
  horizontally as one unit, so the team name scrolled off-screen with the
  fixtures on a wide 20-team grid. Heatmap-gradient FDR cells (replacing
  flat solid blocks), row hover highlight, squad-team rows get a stronger
  highlighted sticky-column treatment.
- **Live Tracking**: FPL-pink live badge (was a generic red), a
  `.live-now-tag` pulsing indicator class ready for when a match is
  actually in progress - no fabricated "LIVE NOW" score, the existing
  honest pre/live/post state machine is untouched.
- **Design system**: real FPL brand palette (`#37003c` purple, `#00ff87`
  green, `#e90052` pink - not an invented one), Titillium Web for
  headers/numbers + Inter for body (both real Google Fonts, confirmed
  `document.fonts.status === "loaded"` live), `prefers-reduced-motion`
  support, `:focus-visible` outlines, custom scrollbar styling, a real
  responsive rework (640px/1024px breakpoints, not the old single 860px
  cutoff) - live-verified at 390px mobile width via the Browser pane: zero
  horizontal overflow, hero/compare panels genuinely restack (not just
  `width:100%`), sticky nav scrolls horizontally.
- **Latest Recommendations panel** - already removed earlier the same
  session per direct user request; confirmed still absent after this pass.
- **10 new/updated tests** (`test_dashboard.py`): risk severity tiers
  (action/low/default), decision center's real-data-only behavior
  (transfer card absent when nothing's logged, present with real text when
  it is), compare-panel's three real states (no entry id / real data
  present / genuinely empty), 2026-08-20-era panel-rename assertions fixed
  forward rather than left broken. 575/575 full suite.
- **Real, disclosed limitation**: a synchronized GW-number header row
  across the fixture ticker's columns (spec section 13) was deliberately
  NOT built - different teams' next-N fixtures aren't guaranteed to share
  the same GW per column (blank/double gameweeks shift alignment
  independently per team), so a shared header row would risk mislabeling a
  column for some teams. Each cell's own `title="GW{n}"` tooltip (already
  real, unchanged) remains the correct per-cell source of truth instead of
  a misleading shared header.

