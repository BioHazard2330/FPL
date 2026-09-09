# Project State

Last updated: 2026-09-10 (frontend Stages 8-14: the app is a football tool - table, calendar, club/player/match pages, season clock - plus a docs and dead-file cleanup). Read this before
resuming work — it's the current, load-bearing snapshot, kept lean on purpose. **Don't add
session narrative here** — a new capability/architecture change gets one short factual entry;
the story of how it was built, bugs found, and live-verification detail goes in `docs/history/`
(one new dated file per session, indexed in `docs/history/README.md`).

**Tooling note (2026-09-03)**: real Claude Code skills were installed/configured
this session — see CLAUDE.md's own "Skills / tooling ecosystem" section for
the full list, what's not installed and why, and the one-time `/impeccable
teach` setup still outstanding before the new frontend-design skills are
usable. No application code changed as part of that pass except two new
project-local skill files.

## Where things stand (updated 2026-09-08, React frontend — Phase 8-10)

The React app (`frontend/`, Vite + TypeScript + Tailwind v4 + shadcn/Base UI)
is now the real, deployed default UI at `/` (the old Python-rendered
`data/dashboard.html` still exists, reachable at `/dashboard.html`, kept as
a real rollback path and the one remaining reference for screens not yet
ported - see below). Backend stays authoritative: a `monitoring/api/*.py`
JSON payload layer (`command_payload.py`/`myteam_payload.py`/`plan_payload.
py`/`football_payload.py`/`scout_payload.py`/`advanced_payload.py`) reads
the SAME `DashboardContext` (`monitoring/dashboard/context.py`, TTL-cached +
proactively refreshed every ~8min by 4 background threads wired into
`LiveServer.start()`) the old dashboard already computed - never a second,
independently-derived calculation. Real, deployed design system: self-
hosted Oswald + IBM Plex Sans (a real bug fixed 2026-09-08 - neither font
had ever actually loaded before that), flat broadcast-graphics palette (no
glow/gradients except a deliberate body-level grain texture + per-screen
atmosphere washes), a compact nav rail, real ApexCharts on LIVE (rank/
points/captain trajectory) and PLAN (trajectory/cumulative-edge).

**Live update model** (real polling added 2026-09-08, Stage 7 - see
`docs/UI_REDESIGN_DECISIONS.md`; every screen fetched its payload exactly
ONCE on mount before this and never refreshed, a real gap this whole
rebuild had carried unnoticed since Stage 2): LIVE polls every 10s
(matches the old dashboard's own real cadence for `live_snapshot.json`);
Command/My Team/Plan/Football/Scout/Advanced poll every 60s (cheap - these
hit the warm server-side `DashboardContext`/per-screen caches almost
always). The shared nav-rail/header chrome (`useLiveMeta`) already polled
independently at 15s and is unaffected. A poll-triggered refetch updates
data in place without flashing back to a loading skeleton, and on failure
keeps the last real data on screen rather than blanking a still-valid
view.

Deploy procedure (manual, not yet automated into `run_scheduled`): `npm run
build` in `frontend/` → copy `dist/{assets,fonts,index.html}` into `data/`
→ restart the real `FPLAgentLiveServer` scheduled task (`Stop-ScheduledTask`
does not actually kill the process - force-kill the real PID first, then
`Start-ScheduledTask`) → warm all 6 `/api/*` endpoints (first hit after a
restart is a real cold `DashboardContext` build - **confirmed ~180s**
2026-09-08 via a direct patient timed request, not the ~60s this module's
own docstring still claims; use a patient timeout when verifying post-
restart, a short one reads a legitimate cold build as a hang).

**Real, disclosed remaining scope** (updated 2026-09-08 - Template Team,
Expected Data, Fixture Ticker, and the MANAGER/XI/AVAILABILITY change wire
are now built, see the dated entry below; each screen has a working, live-
verified v1, these are the specific gaps left, not "incomplete"): SCOUT
(Combobox multi-position/team filter; Statistics panel deliberately NOT
ported - audited and found to be a strict squad-scoped subset of the main
Player Search table, already reachable via its own "My Squad" filter -
porting it would be pure duplication); LIVE (full Match Centre - score/
momentum/shot map - untestable without a live match); PLAN (optional Radial
Orbital view); FOOTBALL (Fixture Projections - the full 20-team x 8-GW
goals/CS% grid, a real, larger, separately-scoped follow-up to the now-built
squad-scoped Fixture Ticker); ADVANCED (Decision Detail, Player Odds,
Optimizer Delta, Regret Analysis). Full narrative (every phase, every bug
found, every live-verification): `docs/UI_REDESIGN_DECISIONS.md`.

## Where things stand (updated 2026-09-08, frontend-wide visual/UX overhaul)

Direct user brief: eliminate every remaining "generic dark SaaS dashboard"
surface across all 7 screens, not just Command - Command was already real,
this pass audited the other six and judged each on its own merits (per the
brief's own "preserve/refine vs fundamentally recompose" distinction, not a
blind full rebuild):

- **Global DESIGN.md conformance sweep**: removed all 14 remaining
  `shadow-[...]`/`drop-shadow-[...]` colored-glow effects across My Team,
  Plan, Football, Scout, and Advanced (Command was already clean from the
  v4 pass) - DESIGN.md's own repeated "flat, no shadow" rule, previously
  violated everywhere outside Command. The one deliberate exception left in
  place: `CommandPalette`'s modal-overlay shadow (a real floating-layer
  elevation cue, not card decoration - judged out of scope for the same
  reason DESIGN.md's own "one live pill" exception exists).
- **My Team**: judged "preserve and refine" (pitch already dominant, real
  bench/pressure/risk zones from the prior pass) - shadows removed, pitch
  column widened (sidebar 240px -> 200px) for more pitch dominance.
- **Plan**: judged "preserve and refine" - the 4 lower sections (path
  comparison / cumulative edge / horizon breakdown / strategy risks) used
  to repeat the same `border-t-2 + eyebrow` pattern four times in a row,
  the exact anti-pattern the brief named; recomposed with the same
  deliberately-varied separation techniques Command's v4 pass established
  (path comparison -> its own flat panel band; cumulative edge -> real
  per-horizon totals as direct chart annotations instead of a separate
  bordered row; strategy risks -> a gold-accented rail).
- **Football / Scout**: judged "preserve and refine" - already had real
  football texture (Fixture Ticker, Change Wire, Template Team, Expected
  Data) from the prior "more football" pass; this pass was shadow removal
  only, structure already sound.
- **Advanced**: judged "fundamentally recompose" - was the worst offender
  (a literal shadow-card grid). Chip Strategy rebuilt as a real horizontal
  comparison rail (chip xP values are directly comparable magnitudes - the
  same broadcast-bar language Command's `ComparisonGraphic` already uses)
  instead of a 2-column card grid. Model vs Market rebuilt as a weighted
  rail where a real `MAJOR_OUTLIER` divergence earns visibly more weight
  than a routine one (the same lead/rest hierarchy `EvidenceRail` uses),
  instead of a uniform boxed list. System Readiness bento grid and Source
  Health table were already sound, kept.
- **Live**: judged "fundamentally recompose" for one real, concrete gap -
  the payload already carried `source_freshness` (per-source last-success/
  degraded flags) and `cadence` (the real adaptive sync interval this
  project's own scheduler uses) but the frontend typed both as `unknown`
  and never rendered them. Added real TS types (`SourceFreshnessRow`,
  `LiveCadence`) and a new System Health section - closes the brief's own
  explicit "control room" hierarchy (status / events / movements / health /
  last-updated), zero new backend computation, purely exposing an
  already-computed real field.
- Full suite run once at the end (no Python changed this pass - a
  confirmation run, not a regression check).

**Follow-up escalation, same day (direct user pushback: "changes are still
small, very minute")** - correct feedback: the pass above was real but
surface-level (shadow removal, band recoloring, one rail conversion). Three
genuine structural rebuilds followed, each a real layout/interaction change
new to this app, not a restyle of what already existed:
- **My Team**: the squad-value/bank/formation/captain/vice strip and the
  "top projected" star-player moment used to be two separate stacked
  sections - merged into one hero band (a real asymmetric split: a compact
  facts column facing the star moment, one shared ghost "SQUAD" numeral
  behind both). Below it, Bench/Transfer Pressure/Squad Risks used to sit
  in a 3-column row UNDER a full-width pitch - moved into a real, wide
  (320px) analysis rail running the full height ALONGSIDE the pitch instead,
  so the pitch stands alone and uninterrupted in the main column while the
  right side carries every supporting fact. A genuinely different page
  silhouette, not the same content re-colored.
- **Plan**: added a new `StrategyGrid` component - real spatial path
  comparison, EVERY shown path laid out simultaneously across the same real
  gameweek axis (rows = ranked paths, columns = the real union of GW events
  any path has a leg for, a cell = that path's real action/chip for that
  GW, an honest empty dash when a path has no leg there). Replaces the old
  single-path rail + separate ranked list with one real overview; the old
  rail (`StepRail`) now serves as the drill-down detail for whichever row
  is selected. Nothing else in this app looks like this - a genuine new
  composition, not a reskin.
- **Scout**: replaced the click-to-open `Sheet` drawer (which slides over
  and hides the table it came from) with a real, always-visible persistent
  detail panel beside the table - the classic scouting-workstation split-
  pane pattern (list left, detail right, selecting a row updates the panel
  in place). A real, honest "select a player" empty state when nothing's
  selected, never a placeholder profile.
- **Real, separately-confirmed operational finding while verifying this
  pass**: a cold `DashboardContext` rebuild (the shared cache every
  `/api/*` route depends on) now genuinely takes **~180s**, not the ~60s
  this module's own docstring still documents - confirmed via a direct,
  patient timed `curl` (177s to first byte) after ruling out every other
  explanation (no duplicate `LiveServer`, no competing scheduled sync, the
  earlier-suspected background test-suite CPU contention indepedently
  ruled out by killing it mid-run with the hang still present). A request
  landing during that real cold window looks identical to a genuine hang
  with a naive short timeout - this is why earlier verification passes in
  this same session misdiagnosed the *same* real symptom differently each
  time (a duplicate process once, suspected CPU contention once). **Real
  lesson for future sessions**: after any live-server restart, verify with
  a patient timeout (3min+) before concluding anything is broken, and
  update `context.py`'s own "~60s" estimate to reality as a real, scoped
  follow-up (out of scope to fix the underlying cost itself this pass).

**COMMAND rebuilt as 8 real, purpose-built compositions** (`frontend/src/
components/command/DecisionHero.tsx`/`ComparisonGraphic.tsx`/
`PlayerGallery.tsx`/`CaptainFaceOff.tsx`/`DecisionHorizon.tsx`/
`StrategyRail.tsx`/`EvidenceRail.tsx`/`ConfidenceGraphic.tsx`), direct user
request ("stop reading as sidebar + stacked bordered sections, read as a
football decision graphic"). `CommandScreen.tsx` is now a thin composition
layer only - zero new backend data, every field traces to the same
`CommandPayload` shape. Each component uses a genuinely different
separation technique (flat colour-field band, one thick rule, or
whitespace alone) rather than the repeated eyebrow+border pattern the
previous pass still had. Two small, real, additive backend fields were
added to support this (never a decision-logic change): `CaptainOption`/
`PlayerBrief` gained a real `team_id`/`team_code` so the captain face-off
can resolve a real shirt without cross-referencing a different payload
block; `PlanStep` gained resolved `player_out`/`player_in` identity objects
for the same reason on PLAN's strategy rail.

**Real DESIGN.md/index.css conformance fix**: the three `.atmosphere-{green,
blue,gold}` radial-gradient "wash" utilities directly contradicted
DESIGN.md's own repeated "no glow, no gradient" rule - removed from
`index.css` entirely (not replaced with another gradient). Command's own
hero/captain-battle no longer reference them; the four other screens that
still did (My Team/Plan/Football/Scout hero sections) had just the
className token stripped - a real, deliberate simplification to a flat
base colour, not a redesign of those screens.

**Real, confirmed operational finding (direct user bug report, "football
tab doesn't work, blue screen for a long time")**: two real bugs, not one.
(1) The loading `Skeleton` component (`bg-muted` against this app's
`bg-void` page background) was near-invisible, especially once
`animate-pulse` dims it further - a genuine ~30s+ cold-cache load (FOOTBALL's
own league-wide signal scan) read as a frozen blank screen. Fixed: `bg-raised`
(real, confirmed higher contrast) plus an explicit "Loading X" text label,
across all 6 fetching screens. (2) The actual reported hang was a SEPARATE,
more serious issue: a second, full `LiveServer` instance (a throwaway dev
convenience script, `dev_live_server.py`, left running by an earlier/
different session on port 8878) was contending with the real production
`FPLAgentLiveServer` (port 8877) for the same real `data/fpl.db` SQLite
file - confirmed live via direct reproduction (`curl /api/command` timed
out completely at 60s with zero response) and confirmed fixed by killing
the duplicate process (both endpoints back to single-digit milliseconds
immediately after). **Real, actionable lesson for future sessions**: never
leave a throwaway `LiveServer`/`npm run dev` instance running past the
session that created it - check `Get-CimInstance Win32_Process -Filter
"Name='python.exe'"` (and `node.exe` for Vite dev servers) for orphaned
processes from prior sessions before assuming a live-server-side bug; a
second full `LiveServer` is exceptionally easy to leave behind since it
deliberately bypasses the real production singleton lock by design (that
lock exists to stop two *scheduled automation* instances from fighting over
writes, not to prevent this exact multi-session dev-instance collision).

**Repository is now public and pushed** (2026-09-08, direct user request -
`https://github.com/BioHazard2330/FPL`, see CLAUDE.md's own "Repository"
section) - lets an external tool (ChatGPT) inspect the real component tree/
payload shapes directly instead of needing a localhost tunnel (tried and
found unreliable: ChatGPT's own browsing environment could not retrieve a
rendered response through either `localtunnel` or a Cloudflare quick
tunnel, both reachable fine by `curl`/this project's own Browser-pane tool
- concluded to be a real limitation specific to ChatGPT's fetch environment,
not a tunnel misconfiguration). **New standing rule** (CLAUDE.md's own
constraints list): commit and push real, verified work to this remote
without waiting to be asked each time - keeps external inspection current.

**Known, unrelated, flagged-not-fixed bug**: `live/sse_server.py`'s 4
background cache-refresh threads can hit a real Python import deadlock on
process start (`_frozen_importlib._DeadlockError`) when two race to import
circularly-dependent `monitoring.api.*` modules - self-heals on retry
(confirmed repeatedly), real fix is eager-importing those modules from the
main thread before spawning the threads. Not yet applied.

## Strategic planner status

`optimization/strategic_planner.py` + `optimization/transfers.py::search_transfer_sequences` — real beam search (default beam width 5, horizon 8 GW), scores full-squad EV summed across the horizon, jointly chip-aware (wildcard/freehit/bboost/3xc compete against ROLL/TRANSFER on the same ranking key at every step, `optimization/chips.py::chip_gw_marginal_value`). `chips.py::schedule_chips`'s Monte Carlo DP (`--with-chips`) is an independent cross-check/opportunity-cost narrative, not the path-selection mechanism. `search_transfer_sequences`/`best_transfer_for_player` price hit cost using the real FT state (`models/free_transfers.py`).

`optimization/transfers.py::compare_starting_actions` + `optimization/strategic_planner.py::synthesize_current_recommendation` compare every real starting action (ROLL, each squad player's best replacement, each legal chip) against its own best full-horizon future and produce one authoritative `CurrentRecommendation` (ACT/REVIEW, same evidence-confidence gate `decision_analysis.py` uses). Surfaced via `fpl strategic-plan --current-action` (default on) and the dashboard's Home hero + Plan workspace. Real production run (locked squad, 8GW horizon): ROLL wins over the immediate 1-GW pick and over PLAY WILDCARD/FREEHIT, consistent with the main search's own top path.

## Decision-object architecture

`optimization.decision_analysis.analyze_transfer_decision`/`analyze_captain_decision` are the single real source of truth for "what should I do." `optimization.decision_engine.evaluate_locked_squad` is a thin KEEP/CHANGE wrapper that derives its answer from an already-computed `ta`/`ca` rather than re-scanning. The dashboard's Home hero (`#home`) and Plan workspace (`#plan`) are the only two places a recommendation renders (frontend redesign, 2026-08-27 - `monitoring/dashboard/home.py`/`plan.py`, replacing the old Primary Decision panel/Strategy Explorer); every other panel either reads from these or is explicitly labeled as answering a different question (Optimizer Delta = from-scratch rebuild comparison, collapsed under Advanced).

## Free-transfer tracking

`models/free_transfers.py::compute_real_free_transfers` replays the real, public FPL accrual rule over already-ingested `my_team_gw_summary.event_transfers` + `my_team_picks.active_chip` history. Returns `None` (never a guess) on a genuine gap in synced history. Wired into `LockedSquadState.free_transfers`, consumed by `analyze_transfer_decision`/`_evaluate_transfer`.

## Known gaps (see CLAUDE.md's "Current known blockers" for the full, current list)

Summarized: Dixon-Coles team-strength ridge (`_RIDGE_LAMBDA=2.5`, fixes a real small-sample-promoted-team overfit) not yet backtest-tuned; bonus/BPS season-grain only; single predicted-lineups source; sampled-EO margin of error computed but not surfaced; cross-league coverage partial (~5 leagues); manager-change signal not wired into prior-shrink speed; team-level qualitative signal deliberately not fed into Dixon-Coles (leakage-safety); Elite-manager panel needs a season to end; penalty-duty adjustment gated on sample size (2 of 20 needed); dashboard regen ~1 minute; `fpl strategic-plan --current-action` (default on) adds real extra cost on top of that (~2-10+ min depending on horizon/beam-width) — a manual command's cost, never re-run live by the dashboard.

## Completed work log (newest last)

Each entry is a real, shipped change. These used to sit under "Next
recommended work", which meant that section listed mostly finished work -
the exact thing that makes a resume document untrustworthy.

1. **Path-diversity - done 2026-08-29** (see `docs/history/19-session-2026-08-29-path-diversity-and-p1-audit.md`): `build_diverse_paths` replaces the raw beam's near-duplicate top-N with `compare_starting_actions`' real per-starting-action options - live-verified against a fresh production run (decision #102): 5 genuinely distinct opening moves (PLAY WILDCARD/PLAY FREEHIT/3 different named-player transfers), not the old single dominant-strategy cluster.
2. **Per-path 3/5/8-GW breakdown - done 2026-08-29**: `checkpoint_breakdown` (bounded to the selected top-N paths only, reuses the shared EV cache) - live-verified real signed `delta_vs_next_best` per checkpoint (positive for whichever path actually leads AT that horizon, not assumed to match the full-horizon leader).
3. **Decision-outcome calibration - done 2026-08-28**: `models/decision_calibration.py`, `fpl decision-backtest` - real deadline-freeze capture + auto-reveal on GW finish, first real GW2 sample captured (pre-deadline, not yet revealed). Still real, scoped work: squad/captain-contribution + actual-vs-expected live charts (data sources identified 2026-08-29 - `prediction_outcomes` + `my_team_picks.is_captain` - not yet built); assist/bonus's 7% correlation gap's real decision-impact (does it ever flip a captain/transfer/BB/FH/TC call, or is it noise the decision layer already absorbs) - not yet checked.
4. **Frontend redesign Phase 2 - done 2026-08-28** (see `docs/history/14-session-2026-08-28-frontend-redesign-phase2.md`): Intelligence workspace now a real league-wide team-signal briefing (`intelligence.py`, calls `team_outlook` across every real team, not just the squad's), Opportunity workspace redesigned into a real scouting board with real confidence per card and a 1-visible-plus-details-for-more cap per category (`opportunity.py`), Market workspace re-framed (`market.py`), Fixture Tool gets real range/metric(overall-attack-defence)/sort/filter controls (`fixtures.py`, reuses the already-built `models.fixtures.fixture_difficulty` - honestly discloses the current preseason attack/defence-strength-not-yet-published fallback). `legacy.py`'s now-fully-superseded orchestrators (`_intelligence_summary_html`/`_opportunity_board_html`/`_market_summary_html`/`_fixture_ticker_html`) deleted, not left dead.
5. **Frontend redesign Phase 3, partially done 2026-08-28**: Squad's projected-GW previews now use real shirt tiles grouped by position (was plain text rows) - see `docs/history/15-session-2026-08-28-visual-density-and-accuracy-audit.md`. Still not done: the `monitoring/dashboard/` module split (legacy.py is still ~4500 lines, mostly Advanced-drawer/Live/Team-Outlook/Match-Intelligence renderers). Fixture Tool's Attack/Defence metrics will start genuinely differentiating from Overall automatically once FPL publishes real attack/defence strength ratings (no code change needed, just currently coincide via an honest, disclosed fallback).
6. **Data sourcing investigation, done 2026-08-28** (see same history file): elevenify.com and Spreadex - the two sources fpl.page itself credits for its projections - are both confirmed NOT viable as automated backend sources for this project (elevenify: single-person Substack, no API/feed, subscription-gated; Spreadex: licensed spread-betting operator, no stable public market data without an account). This project's own Tier-1/2 pipeline (official FPL API, Understat, the-odds-api, BBC/Sky RSS, FotMob) remains the real, disclosed, automatable one - genuinely different methodology from fpl.page's, not a lesser one.
7. **Four new league-wide dashboard panels, done 2026-08-28** (direct fpl.page screenshot comparison - see `docs/history/17-session-2026-08-28-new-panels.md`): Injuries (`injuries.py`, reuses `models.availability.list_availability`), Expected Data (`player_data.py`, real current-season xG/xA/xGI from `player_match_stats_history`), Team Odds and Top Transfers In/Out (`market.py`, league-wide rankings from already-real data). A real historical Odds Tracker line chart is still not built - needs periodic odds snapshotting into a history table, which doesn't exist yet.
8. **Dashboard visual/typography QA at all target breakpoints, done 2026-08-29** (1440/1024/768/360px verified this pass on top of the existing 1280/375 coverage - see `docs/history/22-...md`): zero real page-level horizontal overflow at any width; the two elements a naive scan flagged (`.site-nav`, `.fdr-grid`) are intentional `overflow-x: auto` scroll containers, not bugs.
9. **Opportunity Board "considered by optimizer" flag + Value squad-member exclusion - done 2026-08-29** (see `docs/history/19-session-2026-08-29-path-diversity-and-p1-audit.md`): every card now shows a real yes/no against the diverse-paths candidate pool (never rendered when no strategic plan has run); Value no longer shows an already-owned player as a buy opportunity (real live-screenshot QA finding, matches Breakout's existing exclusion).
10. **P1 product-gap audit, done 2026-08-29; 6 of the "genuinely still unbuilt" items closed 2026-08-29** (see `docs/history/22-session-2026-08-29-fpl-page-parity-p1-features.md`): Points Changes (new - real post-match Bonus/DefCon revision ledger, `models/points_changes.py`, `fpl points-changes`), Template Team + elite-manager context (`template_team.py`, real sampled-EO margin of error surfaced, honest raw-ownership fallback), Price History (`price_history.py`, league-wide search/filter/progress-bar forecast + real confirmed-change ledger, replaces the old squad-only panel), news decision-impact tags (captain/transfer-out/transfer-in, `_news_html`), Fixture Tool Goals/CS% view toggle, dead-CSS/dead-function cleanup (26 CSS rules + 2 functions, scripted audit). **Genuinely still unbuilt**: Top 10K context beyond template/EO, an article feed, a full unified single-view Market redesign beyond the current section-grouped layout, Fixture Tool's "Sort by Rotation" (fpl.page's own metric - no real rotation-risk data source exists per-team to back one honestly; Easiest/Hardest/Squad-first/A-Z sort already exist), Player Inspector click-through redesign (WHY BUY/HOLD/SELL), and decision-outcome calibration (blocked on a season with completed GWs).
11. **Final decision-system completion pass, done 2026-08-29** (see `docs/history/23-session-2026-08-29-final-decision-system-completion-pass.md`): real MODEL vs FOOTBALL/MARKET(Solio)/TEMPLATE cross-check on the Home hero, Points Changes real LIVE/EXPIRED status wired into `live_snapshot.json`, chip strategy why-now/best-alternative explainability, SYSTEM LIVE News/Projections fields, Template Team overlap/differential, Gameweek Projections 3/5/8GW range toggle. **Genuinely still unbuilt, disclosed**: Player Inspector's full BUY/HOLD/SELL/WATCH/REVIEW vocabulary (current per-player inspector is squad-scoped, narrower); intragame live-chart time-series storage (rank/GW-points/squad-contribution/captain-contribution/actual-vs-expected - real, larger infra work, own future session); Fixture Ticker rotation analysis (no real rotation-risk model exists - checked, not faked); full Intelligence-panel editorial restructuring and a structured News→Decision pipeline beyond this pass's own captain/transfer news tags; a dedicated visual-redesign audit against fresh fpl.page screenshots.
12. **Phase 6 complete dashboard rebuild, done 2026-09-03** (see `docs/history/` for the full session narrative): the panel-grid architecture items 7/8/13/14 above describe (Home/Intelligence/Market/Opportunities as separately-promoted panels) is superseded outright, not incrementally extended. The dashboard is now six real, fixed top-level screens - COMMAND (`command.py`, the decision as a state-transition scene), MY TEAM (`myteam.py`, the real pitch + projected-GW switcher), PLAN (`plan.py`, multi-GW path timeline with a real LOCKED-now/CONDITIONAL-future visual convention), FOOTBALL (`football.py`, one real signal feed replacing the old Intelligence/Team-Outlook/Match-Reports panels, folded in with fixture ticker/projections/team odds), SCOUT (`scout.py`, the real Opportunity Board plus Market's ownership/momentum/transfers, Template Team, Price History, Statistics, Expected Data), and ADVANCED (`legacy.py`'s panels, now including Model-vs-Market Divergence). the old `home.py` hero render is no longer called anywhere (its `_action_reason`/`_action_word`/`_freshness_html` helpers are reused by `command.py`, not the module's own old hero markup); the old standalone Market and Opportunity Board panel sections are gone outright, not duplicated underneath the new nav. Full test suite green (1523 passed) after the rebuild.
13. **Frontend Stage 8 - Football/Advanced/Live structural rebuild, done 2026-09-09** (full detail in `docs/UI_REDESIGN_DECISIONS.md`): the three screens earlier stages had only restyled are now genuinely recomposed, and two "open the old dashboard instead" escape hatches are closed. New: a real LIVE match centre (scoreline / opposed team-stat rules / FotMob momentum band / two-half shot map / my players) rendering `live_snapshot.json::active_matches` data that had been fetched every 10s and discarded since 2026-08-29; live bonus + defensive-contribution progress, post-match points revisions, and standing-decision staleness, all previously fetched and unrendered. ADVANCED gained three new real payload blocks (`_decision_audit_block`, `_player_odds_block`, `_points_revisions_block` in `monitoring/api/advanced_payload.py`, all served from that module's existing 600s TTL cache) - the cached `fpl decision-audit` trace is now the screen's dominant object. **Real bugs found and fixed**: the LIVE match-events panel rendered three field names that do not exist on the backend's payload (`minute`/`event_type`/`description` vs the real `kind`/`count`), printing a column of em dashes since the screen was written; `player_odds_live` keeps every historical quote, so the old HTML panel's query returned the same player several times at several prices (confirmed live - Haaland x3), now deduplicated to the newest quote per player; PLAN's cumulative-edge chart rendered fractional gameweek ticks ("6.8"); COMMAND's starting XI was sorted by projected median, putting the goalkeeper eleventh, and now renders as a real GK/DEF/MID/FWD formation with the formation string derived from real position counts. Composition-shaped loading skeletons and one shared, honest error composition (`components/shell/ScreenStates.tsx`) replace the generic grey-rectangle/red-banner pair on all seven screens. Nav gained a Decision/Intelligence/Operations section hierarchy over the same seven routes.
14. **Frontend Stage 9 - DESIGN.md rewritten as the authority + real fixture context everywhere, done 2026-09-09** (full detail in `docs/UI_REDESIGN_DECISIONS.md`): `DESIGN.md` was rewritten end to end after drifting into being actively wrong (it claimed monospace was unused while 15 components used it; described `clip-path` as a core device with one call site; and covered none of charts/motion/loading/error/tables/screen identities). It now opens by stating that where the document and the code disagree, the code is the bug, and adds a Football Language section, a three-motion system, a chart contract, and honesty rules that explicitly outrank aesthetics. New `monitoring/api/fixture_context.py` (read-only, HTTP path only, reuses `models/fixtures.py::team_fixture_ticker` unchanged, ~1ms for a real squad) attaches real upcoming FDR to the COMMAND/MY TEAM/SCOUT payloads, so every player on every pitch now shows their real next opponent, venue and difficulty - a gap `myteam_payload.py`'s own docstring had disclosed since it was written. `components/football/PitchMarkings.tsx` draws real pitch geometry at real proportions on both the My Team squad and the Command action XI. A three-motion system (`.data-in` data arrival, `.bar-draw` magnitude, live pulse) replaces ad-hoc transitions, all disabled under `prefers-reduced-motion`. `lib/chartTheme.ts` and `lib/fdr.ts` collapse four independently-drifting chart configs and two FDR colour tables into one each. **Nothing in the automation path was touched** - no scheduled task, no `run_scheduled` step, no sync cycle; the only backend change is read-only payload shaping on the HTTP request path.
15. **Frontend Stage 10 - the season clock, done 2026-09-09** (full detail in `docs/UI_REDESIGN_DECISIONS.md`): the app now knows what time it is in the football week. `live_snapshot.py::_deadline_block` (two indexed reads, fully wrapped, sub-millisecond) puts the real next/previous FPL deadline on the existing fast-poll channel; `frontend/src/lib/clock.ts` turns that plus the real `gw_lifecycle` state into seven phases (BUILD_UP/IMMINENT/FINAL_CALL/LOCKED/LIVE/SETTLING/REVIEW); `components/shell/MatchdayBar.tsx` renders a persistent broadcast strip on every screen with the phase, a locally-ticking countdown, and - when football is genuinely on - live scorelines, how many squad players are on the pitch and their goals/assists. **Command's section order now changes with the phase**: when the squad can still change the decision leads, and once it is locked or live the XI leads while the decision recedes to a record, with a banner stating that nothing below can be acted on. This closes a real defect, not just a layout gap - Command previously showed the same "PLAY FREE HIT" instruction during a live gameweek when acting on it was impossible. **This is the only change in this work that touches the automation path** (`build_live_snapshot` runs inside the real live-match poll); it is wrapped to degrade to `{}` on any failure and was verified through the real `write_live_snapshot` writer (4.6s, unchanged; all 16 keys intact; still serializable), plus a five-phase browser verification that never writes production state.
16. **Frontend Stage 11 - THE MATCHWEEK screen, done 2026-09-09** (full detail in `docs/UI_REDESIGN_DECISIONS.md`): direct user push - "I get this is an FPL tool but I want it to be a football tool as well." The app had no league table, no fixture calendar and no results; a football fan could not answer "who is top" or "who plays who this weekend". New `monitoring/api/matchweek_payload.py` + `/api/matchweek` (21ms, read-only, HTTP path only) and `screens/Matchweek/MatchweekScreen.tsx` add: a real Premier League table computed from real played fixtures (real points arithmetic, real points/GD/GF tiebreak order, real form guide, real per-match xG/xGA, European and relegation zone marks, the user's own clubs flagged); the real fixture calendar for the last/current/next-two gameweeks grouped by real matchday with real kickoff times rendered in local time; and real full-time detail (possession/xG contest, momentum band, shot map) for any completed fixture, via the same `MatchCard` the live screen uses. That last part closes a real waste: 30 finished matches of FotMob possession/xG/momentum/shot data existed all season and were only ever rendered while a match was in progress. Nav gained a "The football" section holding MATCHWEEK + FOOTBALL, separating the sport from SCOUT's fantasy market. No new data was ingested for any of it.
17. **Frontend Stage 12 - club, player and match pages, done 2026-09-09** (full detail in `docs/UI_REDESIGN_DECISIONS.md`): the app is now browsable as football - every crest and player name is a link. `live/sse_server.py` gained real query-parameter support (a builder opts in by declaring `params`; builders that do not are called unchanged) and turns a `LookupError` into a real 404 so a bad id can never render as an empty page. New `monitoring/api/profile_payload.py` (`/api/club`, `/api/player`) and `monitoring/api/match_payload.py` (`/api/match`), all ~4ms, read-only, HTTP path only. **The player match log is the headline**: 57,200 real per-match rows (minutes/goals/assists/shots/xG/xA/key passes/cards) have existed since the project began with zero frontend presence - every rate the app showed was a season aggregate. Club files carry results from that club's own point of view with real xG beside each scoreline and the full FPL squad; match reports carry a two-sided timeline and BOTH teams' ratings, closing the gap where the live Match Centre only ever listed the user's own players and discarded everything at full time. **Two real data-honesty defects found and fixed while verifying**: 298 substitution events carry no player id at all (excluded from the timeline - an event that cannot be attributed cannot be reported), and `player_match_state.minutes` is NULL for most rows where the first version rendered a fabricated `0'`. 21 new tests, including a bad-id matrix across all three builders.
18. **Frontend Stage 13 - season leaderboards + a real coverage gap closed, done 2026-09-10**: MATCHWEEK gained three real season boards (top scorers, most assists, and underlying xG+xA - the last being the one that leads output), computed from each player's own latest stat snapshot; a player with no snapshot is excluded rather than ranked as a zero. **A real 500 was found by the route sweep and fixed**: an edit of mine deleted the `_TIMELINE_TYPES` constant in `match_payload.py` along with the comment above it, and `/api/match` failed for every real match. The significant part is that the full suite was green throughout - all 23 match/profile tests passed a deliberately bad id and raised `LookupError` before reaching the builder body, so the success path had zero coverage. Closed with an end-to-end test that seeds a real match, goal event, unattributable substitution, team-state row and player performance, and was itself verified by deleting the constant again (fails) and restoring it (passes). Standing lesson for the next parameterised endpoint: a bad-id matrix proves the 404 path, not the payload.

## Next recommended work (real candidates, genuinely not started)

0. **Football features roadmap - large, in progress, 2026-09-10**: direct user request for pure football features (live match visualizations, 3D presentation, real editorial content the FotMob feed already carries and this project never reads) - explicitly not more FPL analytics. Full backlog with real feasibility notes (each claim verified live against the actual endpoint, nothing assumed): `docs/FOOTBALL_FEATURES_ROADMAP.md`. Update that file's own status markers as pieces land; only a one-line pointer belongs here.
1. **Value-of-information folded into `compare_starting_actions`' own ranking**, not just the single-swap decision's separate `information_value_note`.
2. **Team-level qualitative → projection propagation**, done safely (an xG-regression supplement on `team_match_state`, not touching the Dixon-Coles fit itself).
3. **Manager-change → prior-shrink wiring** — a real, scoped, previously-deferred fix.
4. **Surface sampled-EO margin of error** in the dashboard/CLI (currently derived, never printed).

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
