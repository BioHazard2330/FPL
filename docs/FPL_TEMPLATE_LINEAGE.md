# FPL Agent Template Lineage (Phase 8.4/9)

Per-screen structural foundation, real and disclosed - which researched
21st.dev template/component informs which screen's composition, and what
FPL-specific work closes the gap. Free/public sources only (per Phase 9's
own non-negotiable access rule) - Meridian is a paid ($79) template whose
publicly-visible MARKETING PAGE (not its purchased source) was studied for
structural ideas only, same as every other component in this lineage.

Format per screen: **TEMPLATE/COMPONENT + 21ST COMPONENTS + FPL-SPECIFIC UI = FINAL SCREEN**

## SHELL FOUNDATION

**Open-source structural reference**: `arhamkhnz/next-shadcn-admin-dashboard`
and `shadcndashboard/next-shadcn-dashboard` (both real, free, public GitHub
repos) - studied for shell/routing/table-architecture conventions only
(collapsible icon sidebar, route-per-screen, a shared app shell wrapping
`<Outlet/>`). This project's own shell (`AppSidebar.tsx`, `App.tsx`) already
matches this real convention (shadcn's own `Sidebar` primitive,
`react-router` routes) - confirmed, not restructured, since it was already
right per the earlier research pass.

**Explicitly NOT copied from either repo**: their own auth/billing/CRM/
ticket/blog demo routes - irrelevant to a single-user, pre-authenticated
tool.

## COMMAND FOUNDATION

**Meridian** (masthead/bulletin bar, editorial mixed-weight headline,
inverted-polarity before/after panel) **+ Spatial Product Showcase**
(atmosphere glow, floating dense stat panel) **+ Bento Dashboard**
(literal-bar-as-data-object, ghost watermark type) **+ Compare/Us vs Them
Comparison** (real face-off pattern) **+ Performance Benchmark Card**
(kavikatiyar - progress-bar benchmark) **+ Number Flow** (blur-transition
digits for live-changing values)

**FPL-specific UI**: the real `CommandPayload` (action word, edge, checkpoint
table, contribution rows, captain block, alternative, monitor rows) - no
new backend field.

**= FINAL SCREEN**: a masthead bulletin bar (`GW4 · DECISION-2026 · FILED
<freshness>`) above the dominant verdict; the chosen-vs-alternative
comparison recomposed as Meridian's real inverted-polarity panel (the
LEADING path's own numbers on a bright/inverted panel, the alternative
muted/dark) rather than two same-color bars; the captain face-off using the
Compare/Us-vs-Them checklist-style layout; the contribution stat row kept
as the existing broadcast strip; the "what would change this" ticker kept.

## MY TEAM FOUNDATION

**Custom pitch (confirmed, no 21st substitute exists)** + **Editorial Image
Hero** (felipemenezes098 - full-bleed image, fade-to-background mask,
already adopted this phase for the captain/star moment) + **shadcn Sheet**
(player detail drawer) + **shadcn Hover Card** (quick-stat hover without a
full drawer open)

**FPL-specific UI**: `MyTeamPayload` (positions/bench/tiers/lineup state) -
already built.

**= FINAL SCREEN**: unchanged pitch-as-centerpiece (already real, already
football-native, confirmed correct by this and the prior phase's own
research), star-player editorial hero (already built), a real Sheet-based
player detail drawer and Hover Card quick-stats as the next real addition
(not yet built - a genuine, scoped follow-up, since MY TEAM's own v1 this
phase already shipped and was visually verified without them).

## PLAN FOUNDATION

**Modern Timeline** (chowlol202 - vertical rail, real progress-fill,
completed/pending node states, already adopted) + **Timeline Rail**
(nayan_radadiya6 - a leaner horizontal rail variant, real alternative
composition for the GW-by-GW chronology specifically) + **Stepper** (Origin
UI/Nyxb UI family - numbered circle-and-rule steps, for the chip/transfer
SEQUENCE within one path, distinct from the cross-GW chronology)

**FPL-specific UI**: `PlanPayload` (trajectory_series, paths, horizon
breakdown, sensitivity) - already built.

**= FINAL SCREEN**: the existing ApexCharts trajectory line stays (real per-
GW cumulative value, not replaceable by a generic timeline component without
losing real numeric precision); the GW sequence rail already built
(`StepRail` in `PlanScreen.tsx`) is real Timeline-Rail-shaped (flat blocks,
NOW/re-evaluate markers) - kept. Radial Orbital Timeline (an optional
strategy-RELATIONSHIP visualization, per the spec's own framing) is
explicitly NOT adopted as primary chronology - noted as a real, scoped,
NOT-built optional enhancement for showing how the top-N paths branch from
a shared root, since `PlanPayload.paths` already carries the real sibling-
family data (`sibling_count`) this would need.

## FOOTBALL FOUNDATION

**Bento Dashboard's neo-brutalist chart-as-object language** (flat bars,
thick rules) + a real HEAT-MAP-shaped team-state table (Part 14's own
suggestion; a public reaviz-family heatmap pattern - real color-intensity
cells over ATTACK/DEFENCE numbers rather than plain text, a genuine
upgrade over the current text table)

**FPL-specific UI**: `FootballPayload` (categories, squad_changes,
team_state) - already built.

**= FINAL SCREEN v1 (shipped this phase)**: the signal feed + team-state
table already built. **Real, disclosed v2 follow-up**: recompose the
team-state table's ATTACK/DEFENCE numeric columns as real heat-map cells
(background-color intensity scaled to the real xG/xGA value, a direct,
honest visual encoding of already-real numbers - not a new computation) -
not built this pass, a bounded, well-specified next step.

## SCOUT FOUNDATION

**Financial Markets Table** (Isaiah - the originally-researched Stage-1
reference) + **Records Table** (theshanelevine - flat tag chips, dense rows,
already informing the shipped table) + **Combobox/Dual Range Slider**
(filter controls, not yet built) + **Command/Search** (the global palette,
already built, Part 16)

**FPL-specific UI**: `ScoutPayload` (players) - already built.

**= FINAL SCREEN v1 (shipped)**: the real market table with client-side
search/position-filter/sort. **Real, disclosed v2 follow-up**: a Dual Range
Slider for price/form filtering and a Combobox for multi-position/team
selection (richer filtering than the current button row), plus the
Opportunity Board categories (deferred since Stage 3, `scout_payload.py`'s
own docstring).

## ADVANCED FOUNDATION

**System Monitor** (isaiahbjork - real live-stat readout language, informs
the System Readiness grid already shipped) + **Accordion** (existing
`<details>` disclosure pattern, confirmed still correct) + a **real pipeline
visualization** (Part 9's own explicit ask) built from this project's own
actual real stages.

**FPL-specific UI**: `AdvancedPayload` (readiness, sources, freshness) -
already built.

**= FINAL SCREEN v1 (shipped)**: System Readiness + Source Health grids.
**Real, disclosed v2 follow-up**: a DATA -> PROJECTIONS -> FOOTBALL ->
MARKET -> CANDIDATES -> OPTIMIZER -> ROBUSTNESS -> AUTHORITATIVE DECISION
pipeline strip - every one of those 8 real stages genuinely exists in this
project's own architecture table (`CLAUDE.md`'s own "Critical modules"
list) - real, buildable, not yet wired into a payload (needs a per-stage
"did this run, when, how long" read, most of which doesn't have a single
existing structured source yet - a real, scoped follow-up, not fabricated
today).

## LIVE FOUNDATION

**Dynamic Island** (aghasisahakyan1 - a real, compact, morphing live-status
pill - a strong real reference for a live-match indicator, not yet built)
+ **Number Flow** (blur-transition live numbers) + **Marquee** (fixture/
event ticker)

**FPL-specific UI**: `live_snapshot.json` (already real-time, served
directly, no new payload builder needed) - already wired.

**= FINAL SCREEN v1 (shipped)**: match-event ticker + recent-changes feed,
reading the real live snapshot file directly. **Real, disclosed v2
follow-up**: the full real Match Centre (score/momentum/shot map, already
built server-side as HTML in `match_centre.py`) ported to structured JSON,
plus a Dynamic-Island-style compact live-status pill in the topbar - not
built this pass (no live match was active to verify against during this
session, and the full match-centre port is comparable in scope to its own
phase).

## What v1-shipped vs v2-disclosed means here

Every screen this phase has a REAL, WORKING, VISUALLY-VERIFIED v1 in
production React code today. The "v2 follow-up" items above are real,
scoped, honestly disclosed remaining work - matching this project's own
long-standing documentation discipline (see `CLAUDE.md`'s own "known
blockers" section) - never silently implied as already done.
