# Frontend Redesign Decisions — Phase 8.2

Running log of concrete decisions made during the React frontend migration.
Updated as each stage lands. See `docs/UI_21ST_RESEARCH.md` for the component
research and `docs/FRONTEND_MIGRATION_PLAN.md` for the architecture.

## Stage 2 — Scaffold + shell + API boundary (2026-09-08)

**Frontend stack**: React 19 + Vite 8 + TypeScript + Tailwind v4, scaffolded
via `npm create vite@latest frontend -- --template react-ts`, in a new
`frontend/` directory alongside the existing Python project. The pre-existing
root `package.json` (Playwright visual-QA tooling) is untouched and unrelated
- `frontend/` owns its own `package.json`/`node_modules`.

**Design tokens**: ported verbatim from `monitoring/dashboard/legacy.py`'s own
`:root` block (dark-first, `prefers-color-scheme: light` override) into
`frontend/src/index.css`, exposed as Tailwind v4 `@theme` utilities.

**Real, confirmed naming collision found and fixed**: `npx shadcn init`
wanted to define its OWN `--muted` (a background role) and `--accent` (a
hover-highlight role) under the SAME variable names this project already
uses for different things (`--muted` = secondary text color, `--accent` =
the brand green) - it silently appended its own oklch-gray defaults after
ours, so the later definition won. Fixed by renaming this project's own two
colliding roles (`--muted` → `--muted-text`, `--accent`/`--accent-2` →
`--brand`/`--brand-2`) rather than fighting shadcn's convention, since every
future installed shadcn/Radix component's generated Tailwind classes
reference ITS names. `--border` needed no rename - genuinely the same real
concept in both systems.

**Shell**: the official shadcn Sidebar (`@shadcn/sidebar`), collapsible to an
icon rail, 7 real destinations (Command/My Team/Plan/Football/Scout/
Advanced/Live) replacing the old horizontal `<nav>`. Routing via
`react-router-dom` (`BrowserRouter`) - real per-screen URLs, chosen over a
plain in-app switcher per the Migration Plan's own open question.

**`DashboardContext` extraction**: moved out of `assemble.py` into its own
`monitoring/dashboard/context.py` module (`DashboardContext` dataclass +
`build_dashboard_context`), a mechanical, behavior-preserving refactor
verified against the full existing dashboard test suite (one real bug caught
in the refactor itself - `vc_id` wasn't pre-initialized before the
locked/not-locked branch, causing an `UnboundLocalError` in the "no squad
locked" path; fixed and covered by the existing test suite catching it
immediately).

**Real, important performance finding**: `build_dashboard_context` takes
**~60 seconds** against the real production DB (`_analyze_locked_decisions`
~17s, `generate_build_team_report` ~27s) - this was always true of the old
`generate_dashboard_html` too, just previously paid once per periodic `fpl
dashboard` regen, never per-request. A naive per-HTTP-request JSON API would
make every page load pay this cost. Fixed with `get_cached_dashboard_context`
(60s TTL, lock-protected against concurrent-request stampedes) plus a
background cache-warm on `LiveServer.start()` so a real user's first page
load is unlikely to hit a cold cache. **Not yet fully solved**: the TTL
means the API can lag up to 60s behind a genuine change - a real, disclosed
follow-up is tying invalidation to the same materiality-gated trigger
`decision_freshness.py` already uses for the strategic-plan cache, not
attempted this pass.

**API layer**: `monitoring/api/command_payload.py` (first payload builder),
registered in `monitoring/api/API_BUILDERS`, served by new `/api/<screen>`
routes added to the existing `live/sse_server.py` handler (same process, same
port, same CORS posture as the existing `/events` SSE route - no new
infrastructure).

**Real bug found and fixed**: `command_payload.py` initially reused
`command.py::_horizon_label` verbatim, which returns an HTML-entity-encoded
string (`&ndash;`) - correct for the HTML renderer it was built for, wrong
for a JSON API (a React client would render the literal text `&ndash;`, not
a dash). Fixed by converting to a real Unicode en-dash character before
returning it in the JSON payload.

## Stage 3 — COMMAND (2026-09-08)

Built on the Part A composition from the research doc: status strip → hero
(action word + Count Up-animated edge) → contribution stat cards →
Performance-Benchmark-Card-shaped path comparison → captain matchup (same
Benchmark Card component, reused) → alternative panel → monitor log.

**Component reuse**: `BenchmarkCard` (adapted from the researched
kavikatiyar Performance Benchmark Card) is used for BOTH the path comparison
and the captain matchup - one real component, two real call sites, not two
parallel implementations.

**`CountUp`**: hand-recreated from the researched 21st `count-up` component's
own documented API (`to`/`from`/`direction`/`digitEffect` props) rather than
spending one of the account's 2 free daily `21st get` code retrievals on a
component this simple to reproduce faithfully from its own public page.

**Real bug found and fixed during visual verification**: the captain
matchup's `BenchmarkCard` call never passed the player's actual name
anywhere in the rendered output - only "Captain" (the category label) and
the bare median number were visible. Added an optional `valueLabel` prop to
`BenchmarkCard` specifically for this (a named subject distinct from the
card's own category title), fixed both the captain and path-comparison call
sites.

**Verification**: real Playwright screenshots + `inner_text` checks against
the live dev server (backed by the real, warmed, cached `DashboardContext`
against production `data/fpl.db`) confirm the rendered numbers match the
existing HTML dashboard's own values for the same DB state (PLAY FREE HIT,
+8.6 pts edge vs PLAY WILDCARD, Haaland 5.3xP vs B.Fernandes 4.9xP captain
edge, real GW7/8/9 monitor triggers) - not yet a formal byte-for-byte
regression script (see Migration Plan's own per-stage exit checks), but a
real, live-data-verified match.

**Known, not-yet-fixed**: a harmless React console warning
("`asChild`/`aschild` prop on a DOM element") was fully resolved once the
sidebar's `SidebarMenuButton` was correctly wired via Base UI's own `render`
prop (this shadcn version uses Base UI, not classic Radix `asChild`) -
tracked here as a real example of "read the actual installed component's own
types/API, don't assume the demo snippet's exact prop names carry over
unchanged across versions."

## Stage 3 continued — instrument-panel visual pass + production deploy (2026-09-08)

**Direct user feedback**: "Still looks very similar to the old dashboard...
You dont need to have any restrictions per se on creativity really... turn
off the old dashboard and keep this new one as the main thing now." Three
real responses:

**Bolder visual language**: researched 21st.dev THEMES (not just component
modules) via `21st search --type theme` - "Darkmatter"/"Cyberpunk"
(serafimcloud) fetched via `21st theme <id>` (free, unmetered). Took
structural inspiration only (monospace numeric readouts, glow effects,
sharper accent treatment), kept the project's own established brand-green/
FPL-purple-pink identity rather than adopting a generic theme's own palette -
no FPL-specific theme exists on 21st.dev, and this project already has a
distinctive real identity worth preserving. Added IBM Plex Mono ("instrument
panel" numeric font) alongside existing IBM Plex Sans/Oswald. Applied
consistently across `StatCard`/`BenchmarkCard`/`BadgeDelta`/`MonitorLog` and
`CommandScreen`'s own hero/status-strip/alternative-panel: accent bars
instead of plain borders, `font-mono tabular-nums` on every numeric readout,
a brand-glow hero headline (`.glow-brand`, colored by action type - cyan for
chip/transfer, brand-green for roll, amber for review), a progress-bar glow
on `BenchmarkCard`, ▲/▼ arrows on `BadgeDelta`, a subtle body background
texture (radial vignette + hairline grid). Live-verified in the browser
against real production data (port 8878 dev bypass) - genuinely reads as a
broadcast-style decision instrument panel now, not a card-grid dashboard.

**Production deployment - React app is now the default `/`**:
`npm run build` (tsc + vite, clean, 555ms) produces `frontend/dist/`
(`index.html` + `assets/index-*.js`/`.css`, ~130KB gzipped JS). Deployed by
copying `index.html`/`assets/`/`favicon.svg`/`fonts/`/`icons.svg` directly
into `data/` (zero collision with existing `data/` contents - confirmed no
pre-existing `index.html`/`assets/` there). `live/sse_server.py::_serve_static`
changed: root (`/`) now serves the React app's `index.html` instead of
`dashboard.html`; `dashboard.html` stays real and reachable at its own
explicit `/dashboard.html` path (every `ComingSoon` screen's fallback link
still resolves, and it's a real rollback path). Added a real SPA fallback
(any extension-less path with no matching file - e.g. `/my-team`,
`/plan` - serves `index.html` so `react-router`'s client-side routes survive
a direct navigation/refresh) scoped so a genuinely missing asset still 404s
honestly. Widened the static content-type map (`.js`/.css`/`.svg`/`.woff2`/
etc. - previously only `.html`/`.json` had a real MIME type, everything else
fell back to `application/octet-stream`, which would have broken `type=
"module"` script loading in a browser's strict-MIME mode). 3 new tests
(`test_sse_server.py`) - root serves the React shell, an unknown
extensionless path falls back to it, a missing asset with an extension still
404s. 13/14 targeted `test_sse_server.py` tests green (1 pre-existing,
already-documented flaky test - `test_baseline_ids_captured_synchronously_
before_start_closes_a_real_race` - confirmed passes in isolation, same known
thread-scheduling sensitivity under full-suite load noted in `CLAUDE.md`'s
own known-blockers list, not a regression from this change).

**Real, user-confirmed production restart**: the real scheduled
`FPLAgentLiveServer` task's `Stop-ScheduledTask` did not actually terminate
its own live-server process (a real, disclosed Task-Scheduler limitation -
the task's own action process detaches a child the scheduler doesn't track
back to it for stopping) - `Start-ScheduledTask` alone left the OLD process
(PID 17140, serving the old build) still bound to port 8877. Confirmed via
`Get-Process -Id 17140 | Select StartTime` (unchanged, ~25h old) before
acting further. Asked the user directly before force-killing a real,
always-on production process; user confirmed. `Stop-Process -Id 17140
-Force` + `Start-ScheduledTask` produced a genuinely fresh process (new PID,
fresh `StartTime`) now correctly serving the new React build - verified live
via `curl` against the real `127.0.0.1:8877` (root serves the React shell,
`/dashboard.html` still serves the old dashboard, `/my-team` SPA-falls-back
correctly, `/api/command` serves real JSON) and a real browser screenshot
matching the dev-bypass verification exactly.

## Phase 8.3 - full redesign, "The Scoreboard Bug" (superseded by Phase 9 below)

Direct, sharp user rejection of the Stage 3 instrument-panel language as
"AI slop" (dark+glow, monospace-as-costume, glassmorphism) triggered a real
gate check: the `impeccable` skill (`.claude/skills/impeccable/`) requires a
real `PRODUCT.md`/`DESIGN.md` before any design work, explicitly forbidding
synthesis from the user's prompt alone - a genuine one-round interview
(aesthetic lane, theme, anti-references) was run, user picked "Maximalist
broadcast." `PRODUCT.md`/`DESIGN.md` written at the project root defining a
flat, sharp, no-glow broadcast-graphics system ("void/panel/raised" surface
scale, Oswald display + IBM Plex Sans body + tabular-nums data register,
pitch-green/broadcast-gold/broadcast-blue/alert-red palette - a deliberate
break from the FPL brand green/purple). All 7 screens got a real v1 build on
this system (`monitoring/api/{myteam,plan,football,scout,advanced}_
payload.py` all built this phase) - see the full real per-decision log this
phase originally carried below Stage 3 (now folded into Phase 9's own
summary since Phase 9 superseded the COMMAND composition specifically).

## Phase 9 - exhaustive 21st.dev template research + Bulletin Terminal + latency fix

Direct user escalation past Phase 8.3: COMMAND (and by extension the whole
system) still read as "sidebar + hero + metric rectangles + rows" - a
generic dashboard shape regardless of the flat/no-glow palette fix. Real,
substantial work this phase:

1. **21st.dev exhaustive research, two passes** - `docs/21ST_EXHAUSTIVE_
   CATALOGUE.md` (749 distinct real components sampled across all 77 live
   component categories) and `docs/21ST_TEMPLATE_RESEARCH.md` (61 real
   templates across the 7 relevant application categories) - both disclose
   real methodology and a real tool limitation hit mid-session (21st.dev's
   own deep template-page navigation started failing intermittently).
   `docs/FPL_21ST_VISUAL_GRAMMAR.md` and `docs/FPL_TEMPLATE_LINEAGE.md`
   synthesize the findings by visual function and by screen.
2. **Design lab, 3 real candidates** (`frontend/design-lab/`) - Bulletin
   Terminal (Meridian-inspired masthead bar + inverted-polarity comparison
   panel), Neo-Brutalist Broadcast (the existing Phase 8.3 direction), Quant
   Workstation (dense monospace table-first). Rendered at 1440x900,
   compared directly - Bulletin Terminal won clearly (`design-lab/
   DECISION.md`), Neo-Brutalist Broadcast read as comparatively generic once
   seen next to it.
3. **COMMAND rebuilt** on the winning direction, explicit 8-part hierarchy
   (Current decision -> Why it wins -> Alternative strategies -> Captain
   matchup -> Strategic trajectory -> Risk -> What would change this ->
   Football context) - a real masthead/bulletin metadata bar, a mixed-weight
   editorial headline, and a real inverted-polarity (dark vs. bright panel)
   chosen-vs-alternative comparison replacing the flat side-by-side bars.
   **Football context is a real, new backend addition**
   (`command_payload.py::_football_context_block`) - squad-scoped (never
   the league-wide ~650-player scan), with the same duplicate-suppression +
   one-row-per-player diversity cap `football_payload.py`'s own squad-
   changes module already established, reused rather than reinvented.
4. **Masthead rolled out to all 7 screens** (`components/shell/Masthead.tsx`)
   for real cross-screen consistency - Command "FPL Agent Decision Wire",
   My Team "Squad Report", Plan "Strategy Desk", Football "Match
   Intelligence Wire", Scout "Market Desk", Advanced "Systems Desk", Live
   "Live Wire".
5. **Real latency fix - the direct "I want it instantly" complaint.** Root
   cause confirmed live: the 60s cache TTL made the FIRST request after any
   60s gap pay the full ~60-130s `build_dashboard_context` rebuild, AND a
   separate, previously-unnoticed ~20s+ cost inside `run_readiness_checks`
   (a real, full `optimise_squad` pass as its own "Squad optimizer" check)
   hit ADVANCED on every request with no caching at all. Fixed both with the
   same real shape: TTL raised 60s -> 600s (matches this project's own real
   decision-recompute cadence - a 10-minute-old cached view is honest, not
   stale in any way a user would notice), paired with a proactive background
   refresh thread (`context.py::run_context_refresh_loop`, `advanced_
   payload.py::run_readiness_refresh_loop`, both wired into `LiveServer.
   start()` alongside the existing SSE tailer thread) that rebuilds every
   ~8 minutes regardless of traffic - the lazy on-demand rebuild path is now
   a boot-time-only fallback, never something a real user's request pays
   for. **Measured, real, before/after**: cold 44-127s -> warm 60-160ms for
   `/api/command`; cold ~20s -> warm ~90ms for `/api/advanced`. Deployed to
   both the dev-bypass instance and the real scheduled `FPLAgentLiveServer`
   task (same real `Stop-ScheduledTask`-doesn't-actually-stop-it dance as
   Stage 2's own deployment - force-killed the stale PID, confirmed a fresh
   one bound to 8877 afterward).
6. **Dead code removed**: `components/command/{MonitorLog,BenchmarkCard,
   StatCard}.tsx` and `components/ui/badge-delta.tsx` - fully superseded by
   the new COMMAND's own inline JSX, zero remaining importers confirmed via
   grep before deletion. `components/ui/count-up.tsx` kept despite also
   being currently unused - real, scoped near-term need already documented
   (`FPL_21ST_VISUAL_GRAMMAR.md`'s NUMBER ANIMATION section - a blur-
   transition variant for live-updating values, Number Flow-inspired).
7. **New tests**: `test_dashboard_context_cache.py::test_refresh_loop_
   proactively_rebuilds_before_a_request_ever_needs_to`, plus the existing
   `test_api_*` suites re-verified green after the football_context/
   readiness-cache changes.

## Phase 9 continued - the latency fix's own real follow-up bugs, found live

The TTL/proactive-refresh fix above only covered `DashboardContext` and
ADVANCED's readiness checks. Real, live visual QA immediately after
surfaced two more uncached costs that made the "instant" claim untrue in
practice:

1. **COMMAND's own new `football_context` field was itself uncached** -
   computed fresh inside `command_payload.py` on every single request
   (~4-11s, worse under real concurrent load), which meant `/api/command`
   never actually dropped below that floor despite the expensive
   `DashboardContext` rebuild being correctly cached. Fixed by moving the
   computation into `build_dashboard_context` itself
   (`DashboardContext.football_context`, computed once, covered by the
   same cache/refresh cycle) - `command_payload.py` now just reads the
   field.
2. **FOOTBALL's own payload was entirely uncached** - a real ~10-16s
   league-wide signal scan + 20 real per-team `team_outlook` calls, paid on
   every request. Fixed with the same TTL-cache + proactive-refresh shape
   (`football_payload.py::run_football_refresh_loop`, wired into
   `LiveServer.start()` alongside the other two).
3. **Real, external, legitimate contention confirmed during testing**: the
   real scheduled `run_scheduled_hidden.vbs` sync pipeline was genuinely
   running concurrently during several of this phase's own verification
   attempts (confirmed via `Get-CimInstance Win32_Process`), which
   explains why a couple of boot-time warm-up requests took longer than
   the isolated ~41-45s baseline (up to and including one that exceeded a
   150s test timeout) - real, expected, periodic behavior on a single-
   laptop setup running multiple real scheduled tasks against one SQLite
   file, not a bug in the cache itself.

**Final, measured, real production numbers** (after all three fixes,
steady state, `curl` against the real `127.0.0.1:8877`): command 77ms,
myteam 78ms, plan 342ms, football 77ms, scout 110ms, advanced 79ms - every
real screen loads in under 400ms once warm, down from the original 44-130s
per-screen cold cost this phase started from.

## Phase 9 continued - 3 real v2 follow-ups shipped, real production deploy gap caught

Direct user "continue" - picked up 3 of the disclosed v2 items, all frontend-
only (no new backend needed, real data already in the existing payloads):

1. **MY TEAM player detail Sheet** - every pitch/bench tile is now a real
   button; clicking opens a shadcn Sheet with real floor/median/ceiling,
   confidence, expected minutes, tier, lineup detail, armband - all fields
   `MyTeamPayload` already carried, just not surfaced per-player until now.
2. **FOOTBALL heat-map team-state cells** - real color-intensity background
   on the Attack/Defence columns, scaled to each team's own real xG/xGA
   range (`heatStyle`, `color-mix` against the existing palette) - a real
   visual encoding of already-real numbers, zero new computation.
3. **SCOUT max-price range slider** - a real `<input type="range">` filter
   over the already-fetched player list, client-side only.

**Real, critical deployment gap found and fixed while grabbing final
screenshots for proof**: `127.0.0.1:8877` (real production) was still
serving a STALE build from before the entire Phase 8.3/9 rebuild - the dev
server (Vite HMR) had every change, but `npm run build` was never re-run
against the deployed `data/` bundle since the original Stage 2 deploy. A
screenshot of "production" Command still showed the old light-mode glow
design. Fixed: `npm run build` + redeployed (`data/index.html` + `data/
assets/*`, old hashed files removed first) - confirmed via `curl` that
`127.0.0.1:8877/` now serves the current hash, and via a fresh screenshot
that real production Command matches the verified dev build exactly. This
now needs to become a standing step: **any future frontend change requires
`npm run build` + redeploy, not just a dev-server check**, or production
silently drifts from what was actually verified.

## Phase 9 continued - ADVANCED pipeline + LIVE rank pill, final deploy

Two more real v2 items, both frontend-only plus one small real backend
addition:

1. **ADVANCED model pipeline strip** - a real DATA -> FOOTBALL -> PROJECTIONS
   -> CANDIDATES -> OPTIMIZER -> MARKET -> ROBUSTNESS -> AUTHORITATIVE
   DECISION visualization. DATA/FOOTBALL/PROJECTIONS/CANDIDATES/OPTIMIZER are
   a real reorganization of `run_readiness_checks`'s own already-computed
   checks (`advanced_payload.py::_pipeline_block`) - zero new computation.
   MARKET and ROBUSTNESS are two small, real, new additions: MARKET reads
   `latest_solio_snapshot`'s real age (already-existing function, never
   called from any API payload before); ROBUSTNESS reads the SAME
   `authoritative.robustness_class` field `command_payload.py`'s own WHY-line
   already uses. Live-verified against real production: 8 real stages,
   correctly color-coded (DATA/ROBUSTNESS showing real DEGRADED status this
   GW, matching the real DEGRADED odds-API/FRAGILE-decision facts already
   visible elsewhere on the dashboard).
2. **LIVE rank pill** - the masthead now shows the real live-rank estimate
   (`live_snapshot.json`'s own `rank.estimated_rank`), muted when
   `is_current` is false (an honest "not current" label, never presented as
   fresher than it is) - zero new backend work, this field was already in
   the live snapshot and simply unused until now.
3. **My Team player Sheet fix carried through cleanup**: unused dead
   component files were NOT reintroduced; new components (`sheet.tsx`
   consumption) reuse the existing shadcn primitive.

**Final full suite run**: 1669/1669 passed (up 1 from the previous 1668 -
the new `test_advanced_payload_pipeline_groups_real_readiness_checks_by_
stage` test), ~16m12s.

**Final production redeploy + verification** (`npm run build` + real asset
swap + real scheduled-task restart, same force-kill-the-stale-PID pattern
as every prior deploy this phase): all 6 real `/api/*` screens confirmed
steady-state under 250ms against `127.0.0.1:8877` (command 77ms, myteam
61ms, plan 237ms, football 77ms, scout 94ms, advanced 109ms).

## Phase 9 continued - SCOUT Opportunity Board, cached from the start

The real Opportunity Board (Breakout/Fixture Swing/Role Change/Value/Trap -
`opportunity.py`'s own real category scans: `find_breakouts`/`find_traps`/
setpiece-order-change SQL/price-rise SQL/fixture-quality scan) is now a real
JSON payload (`scout_payload.py::_build_opportunities`) and rendered on
SCOUT above the market table - same real per-category cap (3), same real
"why now"/risk/confidence fields, same real squad-exclusion logic, reshaped
from HTML rows into JSON rows rather than a second/different scan.

**Applied the latency lesson from earlier this phase before shipping, not
after**: `find_breakouts`/`find_traps` are real, non-trivial league-wide
scans, so this payload was cached (TTL + proactive refresh, wired into
`LiveServer.start()`) from its first commit - no live "why is SCOUT slow"
regression this time. Live-verified against real production: Mitchell/
Acheampong/Boscagli (Breakout), Lukić/Davis/Fatawu (Role Change), Isak/De
Cuyper/Rogers (Value), Mbeumo/Semenyo/Dubravka (Trap), Crystal Palace
(Fixture Swing) - all real, current candidates matching the old dashboard's
own real numbers.

**Final deploy this round**: `npm run build` + redeploy + real scheduled-
task restart (same pattern). All 6 real `/api/*` screens confirmed warm and
steady-state under 300ms against `127.0.0.1:8877` (command 62ms, myteam
84ms, plan 267ms, football 67ms, scout 62ms, advanced 63ms) - this time
every endpoint warmed cleanly on the first boot cycle with zero timeouts,
confirming the earlier real sync-job-contention theory (not a caching bug).

## Phase 10 - full art-direction pass (2026-09-08, direct harsh user rejection of the Phase 9 end state: "looks so plain... no themes... lack of football")

Real, sequential fixes, each verified live against production before moving
to the next (dev-bypass on 8878 first, then rebuilt/redeployed/warmed
against the real scheduled `FPLAgentLiveServer` task on 8877 every time):

1. **Root cause of "bland/generic 4th-grader" look, found and fixed**:
   `frontend/public/fonts/` didn't exist at all. Oswald had zero `@font-face`
   rule anywhere; IBM Plex Sans's own rule pointed at a file that had never
   been created. Every `font-display` headline across the entire app had
   been silently rendering in the fallback system sans-serif this whole
   redesign - the one device meant to carry this system's typographic
   identity was never actually on screen. Fixed by downloading and self-
   hosting the real variable-weight woff2 files for both families (one file
   per family covers the full weight range Google serves).
2. **Visual richness pass**: a body-level SVG-noise grain overlay (broadcast-
   truck material feel), stronger atmosphere-wash gradients (13-16% ->
   22-26% + a second corner glow), a large per-screen background watermark
   word (PLAN/MATCH/MARKET/ENGINE/SQUAD, matching Command's existing GW
   watermark) so each screen reads as its own territory.
3. **Component/depth pass** (direct follow-up complaint: "no components"):
   Command's decision headline became a real angled `.verdict-block` banner
   (solid fill + drop shadow) instead of plain text; real shadow/depth added
   to every bar/card/badge/table across Command/Plan/My Team/Football/
   Scout/Advanced/CommandPalette so surfaces read as physical objects.
4. **A real, app-wide horizontal-overflow bug found and fixed**: every
   screen was silently overflowing ~200px past the real viewport width
   (confirmed via `document.documentElement.scrollWidth` vs
   `window.innerWidth`) since the sidebar-width customization earlier this
   phase - root cause was `SidebarInset` (a flex item) lacking `min-width:
   0`, so its own oversized children forced it wider than its flex-allotted
   space instead of shrinking. One-line fix (`min-w-0` on `SidebarInset` in
   `App.tsx`) resolved it everywhere at once - found while chasing why a
   MAJOR_OUTLIER badge wasn't visible on ADVANCED.
5. **MY TEAM real Hover Card** (closes a Phase 9 disclosed-remaining item) -
   floor/median/ceiling + confidence/expected-minutes/lineup on hover, full
   Sheet still opens on click.
6. **ADVANCED "Model vs Market" module** (closes another Phase 9 disclosed
   item) - real Solio divergence list (`advanced_payload.py::_build_
   benchmark_block`, reused `top_divergences`/`latest_solio_snapshot`
   verbatim from `benchmark.py`), cached alongside readiness (same TTL +
   proactive-refresh thread).
7. **ADVANCED "Chip Strategy" module** (closes another Phase 9 disclosed
   item) - real eligible-chip values + why-now/best-alternative/timing-edge
   explanation, reused `legacy.py::_chip_strategy_html`'s exact real data
   (`eligible_chips`/`bench_boost_value`/`triple_captain_value`, decision-
   journal reads for wildcard/freehit/season-sim explanations) as JSON.
   **Real bug found and fixed in the same pass**: `sse_server.py::
   _readiness_refresh_main`'s own one-time boot warm call still called
   `_get_cached_readiness(conn)` with no squad ids (only the periodic loop
   function had been updated), so it cached an empty chip list for the full
   10-minute TTL before any real request could correct it - fixed at all 3
   real call sites.
8. **FOOTBALL "Team Odds" module** (closes another Phase 9 disclosed item) -
   real next-fixture clean-sheet-%/projected-goals ranking, reused `market.
   py::render_team_odds_html`'s exact real primitives (`team_fixture_
   ticker`/`clean_sheet_probability`/`_cached_fixture_goals_for`) as JSON,
   rendered as a real bar-ranked list rather than a table (visual
   consistency with the rest of this phase's bar-composition language).
9. **Direct user complaints answered one at a time, each a real fix, not a
   restyle**:
   - *"don't see the free hit team although it says to freehit"* - COMMAND
     now shows the real recommended action's actual 15-player squad
     (starting XI + bench + captain/vice), resolved via `resolve_projected_
     xi` against `TransferSequenceStep.resulting_squad_ids` (a real field
     that already existed in the decision journal specifically to solve
     "what does a wildcard/freehit squad actually look like" - built
     2026-08-29, never read by any dashboard panel until now). Computed
     once in the cached `DashboardContext` (`context.py::action_squad`),
     never per-request - same lesson as the earlier `football_context`
     latency fix.
   - *"nothing is refreshing live... says 4h ago"* - the nav rail/header
     status dot claimed "live" (green) purely because a fetch succeeded,
     regardless of how stale the underlying snapshot actually was - a real,
     direct violation of this project's own "never label data live outside
     its freshness window" rule. Fixed: green only when the real
     `generated_at` timestamp is under 5 minutes old; gold ("synced (idle)")
     when connected but stale; the label itself changed from "Data live" to
     "Synced" to stop conflating chrome-connectivity with match-liveness.
   - *"no amazing graphs... lack of football"* - real season-long ApexCharts
     (rank trajectory, cumulative points, captain contribution) now render
     on LIVE, sourced from `live_charts.py`'s own real `_rank_series`/
     `_cumulative_points_series`/`_captain_contribution_series` (single
     indexed SQL SELECTs over `my_team_gw_summary`/`my_team_picks`, cheap
     enough for every live-snapshot poll) - real data that had existed
     server-side since 2026-08-29 for the old HTML dashboard but was never
     exposed to the new JSON API at all.
10. **SCOUT "Price Moves" module** - real rise/fall forecast (uncalibrated
    momentum heuristic, `price_forecast.classify_price_change`) + confirmed
    price-change ledger, reused `price_history.py`'s exact real SQL/
    heuristic as JSON, bounded to the top 24 real movers (never the full
    league scan).
11. **Real analytical detour, not UI work**: direct user question ("why so
    many Solio outliers if Solio is regarded as accurate") traced to a real,
    concrete mechanism - every current MAJOR_OUTLIER player has under 4 real
    2026-27 matches (`_MIN_MATCHES_FOR_HIERARCHICAL_PRIOR = 4`), so this
    model's own hierarchical shrinkage prior still dominates their hot
    current-season start (confirmed live: Isak's real per-90 goal rate 1.10
    this season, shrunk to 0.36; Palmer 0.68 -> 0.29; João Pedro 0.67 ->
    0.33 - `PRIOR_STRENGTH_MATCHES = 10` means a 3-match sample only carries
    ~23% weight). Real web research on the follow-up "Solio/FPL Review are
    more accurate" claims found genuine community reputation for both but
    zero independent accuracy benchmark for Solio anywhere; FPL Review's
    paid Massive Data Model DOES have one real independent benchmark
    (arXiv 2508.09992, OpenFPL vs FPL Review, prospectively tested on real
    2024-25 gameweeks) - beats a naive baseline by 5-34% RMSE, strongest at
    low-return players. FPL Review's Massive Data Model is paid ($4.50/mo)
    so it can't become a live benchmark connector under this project's
    free-resources-only rule; its free-tier model exists per FPL Review's
    own docs but the live site's own Projections page was confirmed broken
    ("Back Soon - Page under development") when tested directly, so no new
    connector was attempted. OpenFPL itself (free, MIT-licensed) was
    evaluated and NOT adopted as a second benchmark source: it's a same-
    family statistical/ML model (XGBoost/Random-Forest ensembles trained on
    historical FPL/Understat stats, per its own paper) - methodologically
    close to our own approach, not the kind of genuinely orthogonal cross-
    check Solio's market-odds-based signal provides - and it ships as a
    6-commit research artifact (notebook-driven, no live API/package, no
    confirmed retraining for the current season), a real, separate build
    project if ever pursued, not a drop-in connector. No model change was
    made to this project's own shrinkage strength - real, disclosed, open
    question (is 3-match shrinkage too conservative, or is Solio overreact-
    ing to early-season noise) that only a real walk-forward backtest could
    settle; offered, not yet run.

Full test suite not re-run this phase (targeted files only, per the
established "targeted first, full suite before declaring done" workflow) -
see individual commits for exact targeted-test evidence. Every backend
change in this phase re-verified with real production data via the dev-
bypass server (8878) before every redeploy to the real scheduled task
(8877); every screen re-checked for the real overflow bug (item 4) after
its own fix.

## Remaining, honestly disclosed scope (Phase 10 end state)

- **SCOUT**: Combobox multi-position/team select (richer than the current
  button row); Template Team/Statistics/Expected Data panels - real in the
  old dashboard, not yet ported (Opportunity Board, Transfer Momentum, and
  Price Moves all shipped across Phase 9/10, see above).
- **LIVE**: the full real Match Centre (score/momentum/shot map,
  `match_centre.py`) is not yet ported to structured JSON - genuinely
  untestable this session too (no live match was active at any point).
  Live Squad Impact + real season charts (rank/points/captain) shipped this
  phase as a real, if partial, substitute.
- **PLAN**: the optional Radial Orbital strategy-relationship view (a
  secondary visualization, not a chronology replacement).
- **FOOTBALL**: the MANAGER/XI/AVAILABILITY changes feed, Fixture Ticker,
  and Fixture Projections panels remain HTML-only in the old dashboard
  (Team Odds shipped this phase, see above).
- **ADVANCED**: Decision Detail, Player Odds, Optimizer Delta, and Regret
  Analysis remain HTML-only in the old dashboard (Model vs Market and Chip
  Strategy both shipped this phase, see above).
- **Model validation**: a real walk-forward backtest comparing this
  project's own shrinkage-strength choice against Solio's apparent lower-
  shrinkage/higher-responsiveness behavior for low-sample early-season
  players - a real, scoped, offered-but-not-yet-run follow-up (see item 11
  above).
- **A real, pre-existing, unrelated bug found and flagged but not fixed
  this phase** (spawned as a separate task, `task_a901aded`): `sse_server.
  py`'s 4 background refresh threads each do their own `from fpl_agent.
  monitoring.api.X import ...` as their first action, which can deadlock
  (`_frozen_importlib._DeadlockError`) when two threads race to import
  circularly-dependent modules on a fresh process start - self-heals on
  retry (confirmed live, repeatedly), real fix is eager-importing every
  `api.*` module from the main thread before spawning the 4 threads.

## Stage 4 — art-direction pass v3 ("more football") + COMMAND visual composition rebuild v4 (2026-09-08)

Two separate direct-user-driven passes landed together this session; both
kept to the same standing rule (real payload data only, no backend
decision-logic changes, no new architecture beyond what each pass actually
needed).

**Art-direction pass v3 - real football texture + backend extensions**
(direct user follow-up to the Phase 8.0-8.3 redesign: "more football, less
AI slop"):
- **Real, confirmed bug found and fixed**: the FPL shirt CDN only serves
  three discrete sizes (66/110/220px) - every other pixel value silently
  404s (`img.complete=true`, `naturalWidth=0`, no console error, no visible
  broken-image icon). A prior tier-size gallery pass had introduced
  arbitrary sizes (92/116/148/etc) that were all quietly failing. Fixed at
  the source in `lib/api.ts::shirtUrl` - every caller now snaps to the
  nearest real size, verified via direct fetch against the real CDN.
- **FOOTBALL**: real squad-scoped Fixture Ticker (FDR-coloured, real
  `team_fixture_ticker`) and a real MANAGER/XI/AVAILABILITY change wire
  (the same real `change_events` table the old dashboard's `_squad_changes_
  html` already read, reshaped as clean JSON - no HTML entities leaking
  into React-rendered text, the same class of bug this project's own
  `command_payload.py` had already found and fixed once for `_horizon_
  label`).
- **SCOUT**: real Template Team board (highest-owned pool per position as
  actual shirts on a turf strip, real squad-overlap/differential stats) and
  a real xGI-per-90 leaderboard (a genuinely non-redundant signal over the
  main table's raw-total xGI - surfaces a high-rate player under-ranked by
  fewer total minutes). Statistics panel deliberately NOT ported - audited
  and found to be a strict squad-scoped subset of data the main table
  already exposes via its own "My Squad" filter.
- **PLAN**/**COMMAND**: real player-identity backend extensions
  (`CaptainOption.team_id`, `PlanStep.player_out`/`.player_in`) so the
  frontend can resolve a real shirt without cross-referencing a different,
  possibly-non-matching payload block.
- 8 new backend regression tests; full suite 1675/1675 clean at the time.

**COMMAND visual composition rebuild v4** (direct user brief: stop reading
as "sidebar + header + stacked bordered sections", read as "a football
decision graphic / editorial command centre" - COMMAND only, no other
screen restructured, no backend rewrite, no framework migration):
- `CommandScreen.tsx` rebuilt as a thin composition layer over 8 real,
  purpose-built components (`components/command/DecisionHero.tsx`/
  `ComparisonGraphic.tsx`/`PlayerGallery.tsx`/`CaptainFaceOff.tsx`/
  `DecisionHorizon.tsx`/`StrategyRail.tsx`/`EvidenceRail.tsx`/
  `ConfidenceGraphic.tsx`) - zero new backend data, every field traces to
  the same `CommandPayload` shape the previous version already rendered.
- Each component uses a genuinely different separation technique (a flat
  colour-field band, one thick rule, or whitespace alone) rather than the
  repeated eyebrow+border pattern the earlier passes still leaned on
  everywhere - the explicit anti-pattern the user's brief named directly.
- **Real DESIGN.md/index.css conformance fix**: the three `.atmosphere-
  {green,blue,gold}` radial-gradient utilities directly contradicted
  DESIGN.md's own repeated "no glow, no gradient" rule - removed entirely
  (not replaced with another gradient); the four other screens still
  referencing the class names had just the token stripped (a real
  simplification to their flat base colour, not a redesign of those
  screens - explicitly out of this pass's own scope).
- All colored `shadow-[...]`/`drop-shadow-[...]` glow effects removed from
  COMMAND's own hero/verdict-block/bars/shirts - DESIGN.md's "flat, no
  shadow" rule, previously violated throughout this screen specifically.

**Operational fixes found while investigating a direct user bug report**
("football tab doesn't work, blue screen for a long time") - two real, of
separate causes:
1. The loading `Skeleton` primitive (`bg-muted` against this app's
   `bg-void` background) was near-invisible - a genuine ~30s+ cold-cache
   FOOTBALL load read as a frozen blank screen. Fixed: `bg-raised` (real
   confirmed higher contrast) + an explicit "Loading X" label, all 6
   fetching screens.
2. The actual reported hang: a second, full `LiveServer` instance (a
   throwaway dev-only script left running by an earlier/different session
   on port 8878) was contending with the real production server (port
   8877) for the same `data/fpl.db` SQLite file - confirmed via direct
   reproduction (`curl /api/command` timed out completely at 60s) and
   confirmed fixed by killing the duplicate (both endpoints back to
   single-digit milliseconds immediately). See `docs/PROJECT_STATE.md`'s
   own dated entry for the full real, actionable lesson this leaves for
   future sessions (check for orphaned `LiveServer`/Vite processes from
   prior sessions before assuming a live-server-side bug).

**Repository made public and pushed** (`https://github.com/BioHazard2330/
FPL`, direct user request - lets ChatGPT inspect the real implementation
directly after its own browsing environment proved unable to retrieve a
rendered response through either `localtunnel` or a Cloudflare quick
tunnel, both independently confirmed reachable by `curl` and this
project's own Browser-pane tool). Committing and pushing real, verified
work to this remote without being asked each time is now a standing rule
(CLAUDE.md's own constraints list).
