# 21st.dev Component Research — Phase 8.2

Research pass for the FPL Agent frontend rebuild. Every component below was opened
on 21st.dev directly (preview + Usage.tsx/Component.tsx code inspected, not judged
from a screenshot alone), searched via the authenticated `21st` CLI (`21st search`,
free/unmetered) and the public component pages (also free — Usage/Component code is
shown to any visitor, no login needed to read it).

**Stack reality**: every component below is React + Tailwind (+ shadcn/Radix for
most). None of it runs as-is inside the current Python-generated HTML/vanilla-JS
dashboard. Per the approved architecture decision, the frontend is being rebuilt as
a real React/Vite/TypeScript/Tailwind app (`frontend/`) specifically so these
components (and the shadcn/Radix primitives most of them depend on) can be adopted
close to their real implementation — see `docs/FRONTEND_MIGRATION_PLAN.md` for the
Python↔React boundary. The Python backend (optimizer, projections, decision engine,
football intelligence, all data) is unchanged and stays authoritative.

**Sourcing standard applied** (per spec Part 15): "adapt" = same structure/props,
reskinned to our tokens and wired to our real data. "Reference only" = the
interaction idea is worth reusing but the concrete component doesn't fit closely
enough to install directly (wrong data shape, wrong domain, or a weaker
implementation than what we can build directly on our own primitives).

**Revision note (round 2)**: the first pass covered shell/command/plan/scout/
football/player/advanced/live at a *module* level. This revision adds the six
requested gap areas (Command page composition, player-vs-player comparison,
command palette depth, advanced filtering, dense data workspace, motion/
micro-interactions), and — the actually load-bearing part of this document — a
**page composition** for all seven screens: one dominant visual idea each, with
these components as its internal pieces, not a pile of cards.

---

## PART A — Page Compositions (read this first)

Per-screen: the one idea that must be true at a glance, then how the researched
components serve it. Every field named below is a real, already-computed value
this project's backend produces today — nothing here invents a new metric.

### COMMAND → the decision

One verdict dominates. Everything else is evidence for it, not a peer.

1. **Status strip** (existing, kept) — GW badge, `Status` pill (live/stale/
   recomputing), squad value/bank/FT as compact inline chips. Not full KPI
   cards — this is context, not content.
2. **Hero** (existing large-type action headline, kept as-is — this is already
   the right idea) — `PLAY FREE HIT`, the edge in points rendered with
   **Count Up** (springs to `+8.6 pts` when the payload arrives/changes — a
   real data-arrival event, not a load flourish), one-line why.
3. **Alternative comparison, right rail** — rebuilt on the **Performance
   Benchmark Card** shape: THIS PICK's path-total as the big headline value
   with a benchmark-average marker (= the strongest alternative's own total)
   on a horizontal track, then a ranked "main alternatives" list (the real
   `sd['paths']` diverse paths, already computed) each with its own **Badge
   Delta**. Replaces today's plain 3GW/5GW/8GW table with something that
   reads at a glance instead of requiring column-scanning.
4. **Why the model prefers this** — the existing TRANSFER/CHIP EDGE, CAPTAIN
   EDGE, OPTIONALITY row becomes three **Stat Cards**, each number a **Badge
   Delta**.
5. **Captain matchup** — same Performance Benchmark Card pattern reused:
   Haaland as the headline, B.Fernandes as the one "main competitor" row,
   the real edge-driver text underneath.
6. **Trajectory teaser** — a compact, read-only **Timeline Rail** (NOW → next
   2–3 legs only) linking through to the full PLAN screen — never a
   duplicate of Plan's own detailed content, just a preview.
7. **What would change this** — real trigger/condition/consequence rows,
   given the **Interactive Logs Table** row treatment (condition, trigger,
   consequence columns; this is genuinely log-shaped data).

Explicitly NOT: a grid of 8–12 equal-weight cards. Every element above has a
different visual weight, in the order listed.

### MY TEAM → the tactical squad

The pitch is the page. Everything else frames it.

1. Status strip (formation/value/bank/FT) — unchanged, small.
2. **The pitch** — hand-built, unchanged (real shirts/crests; no 21st
   component exists for this, confirmed by direct search — see §5).
3. Right rail — Top Projected / Weak Links, kept as the Phase 8.1 rule-line
   list; a weak-link name gets a **Hover Card** micro-preview (xP/fixture/
   risk) so a user can glance without opening the full inspector.
4. **Player inspector** = **Sheet** sliding from the right on tile click:
   header (shirt/crest/name/price/position), real stat rows (xP/actual/
   expected minutes/fixture/risk/football signals — everything the current
   drawer already shows), plus a **Radar Chart** of the player's own
   attribute shape (Goals/Assists/xG/xA/Bonus/Minutes-security) — the one
   genuinely new capability here, built from data `expected_points()`/
   `player_regression.py` already compute per player.
5. GW tabs (CURRENT/GW4…GW11) become the **Segmented Control**.

### PLAN → the trajectory

A rail you trace with your eyes from NOW to the horizon.

1. Header — leading strategy label, edge-vs-roll (**Badge Delta**),
   confidence.
2. **Timeline Rail** — NOW → GW4 → GW5 → … → horizon, filled progress for
   locked-in legs, dimmed for conditional ones, dot color keyed to the
   existing leading/alt/roll role palette.
3. **Modern Timeline**, expanded detail for the *selected* path only (not all
   3 alternatives stacked at once) — each real step's action, the real "why
   this beats roll" text, chip/transfer detail, a status pill (locked-in /
   conditional / re-evaluate, matching the existing dashed-vs-solid
   distinction).
4. Path comparison list — unchanged real interaction (click a row, swap what
   the Rail+Timeline show), each row's edge now a **Badge Delta**.
5. By-horizon (3/5/8GW) — three **Stat Cards**.
6. Chip timing — stays a plain real list, already minimal.
7. What would change this — same **Interactive Logs Table** treatment as
   Command (shared component, shared visual language for "trigger" data
   across screens).

### FOOTBALL → league + match intelligence

Scannable signal density, not a text wall.

1. Status strip (signals tracked / N affect your squad).
2. "What Changed For My Squad" — kept as its own bordered module (Phase 7.3
   decision, still correct), rows tightened using the same evidence/
   interpretation/consequence structure already built this phase.
3. **Team State** (already a real table, this phase's own Phase 8.1 fix) —
   gains the **Records Table**'s sticky-first-column treatment once scrolled
   (crest+name pinned, ATTACK/DEFENCE/TACTICAL/FPL IMPLICATION scroll under
   it).
4. League-wide signal feed — a **Segmented Control**/filter-chip row per
   category (Creation/Goal Threat/Set Pieces/Minutes) so a user can filter
   the feed instead of always seeing every category at once — a real, new
   interaction, not just a visual reskin.
5. A team row gets an optional **Hover Card** with that team's own
   attack/defence **Radar Chart** for a quick-glance comparison.
6. Match Evidence — stays a collapsed disclosure (already correct).

### SCOUT → the player market

A real market terminal: search → filter → compare → act.

1. **Toolbar**: search (Combobox-style autocomplete), **Segmented Control**
   position filter, **Dual Range Slider** price filter, a sort dropdown — one
   real filter bar, replacing today's single search box + plain buttons.
2. **Main table** = **Financial Markets Table** shape: crest, name+team,
   price+Δ (**Badge Delta**), owned%, points, form, xGI, an inline sparkline
   built from the SAME per-match series `render_player_form_chart` already
   computes server-side. Row click → the shared **Sheet** inspector.
3. **Opportunity Board** — recomposed onto the SAME row shape as the main
   table (one consistent table language across the whole screen, not two),
   grouped by category (Breakout/Fixture Swing/Role Change/Value/Trap); "N
   more candidates" becomes a real **Expanding Sub-Rows** reveal instead of a
   separate nested `<details><table>`.
4. Recruitment scatter (Price vs xP) — kept, ApexCharts, already justified.
5. Transfer Momentum / Template Team — compact two-column lists, each row a
   **Ticker**-style chip (crest+name+count).

### ADVANCED → the analytical workstation

Dense and unapologetically technical — the one screen where that's the goal.

1. Module list stays native `<details>` per module (Decision Detail/Chip
   Strategy/Model vs Market/Player Odds/Optimizer Delta/Independent Model
   Benchmark/System Health/News/Injuries/Points Changes) — zero-JS-required
   disclosure is a genuine strength here, not something to replace with a JS
   accordion just for its own sake.
2. **System Health / readiness / source-status** — rebuilt on the
   **Interactive Logs Table** shape: timestamp, source, a real OK/DEGRADED/
   FAIL status pill, one-line detail, expandable row for the full detail —
   directly replacing today's plain colored-dot chip grid.
3. **Points Changes / Player Odds / Model vs Market** — **Records Table**
   shape: sticky player-name column, colored tag chips for divergence class
   (AGREEMENT/MINOR/MATERIAL/MAJOR_OUTLIER).
4. Decision Audit trace — kept as its own real causal-chain disclosure; each
   step can reuse Modern Timeline's status-pill treatment (shared language
   with Plan's own step list).

### LIVE → the match centre

Broadcast feel, big score, real-time pulse.

1. Genuinely live match: crest+score+minute header, stat-comparison bars,
   momentum/shot-map chart, "my players" live row — all existing, real,
   unchanged content, rebuilt in React with the same visual language.
2. Squad Live Tracking (season charts + own live bonus/DEFCON) sits below in
   the same screen (this phase's own Phase 8.1 structural fix, kept) — live
   points/rank numbers use **Count Up** as real SSE pushes land.
3. Live event feed (goals/cards/subs) — an **Activity Feed** row shape
   (colored icon-badge + player + timestamp).
4. **Status** atom for the LIVE/HALFTIME pulsing indicator.
5. A genuinely new real-time event (e.g. a goal involving a squad player)
   triggers a **Toast Notification** if the tab is open in the background —
   informational, tied to a real event, auto-dismissing. See Part D for why
   this is the tasteful version of "animate on live data," not the rejected
   "animate on page load."

---

## PART B — Component Directory

Format: Component · 21st URL · Purpose · FPL Agent destination · Integration
notes · Dependencies · Decision. "Handoff" = what the component's own
Usage.tsx/Component.tsx code (read directly, this is the practical equivalent
of its Copy Prompt for our purposes — same source, same author-provided
implementation) actually specifies, which is what we build from — never a
visual guess from a screenshot alone.

### B1 — Application Shell

| Component | 21st URL | Purpose | FPL Agent destination | Integration notes | Dependencies | Decision |
|---|---|---|---|---|---|---|
| **Sidebar** (official shadcn/ui) | https://21st.dev/@shadcn/components/sidebar | Persistent collapsible app nav | Replaces `<nav class="site-nav">` entirely | `SidebarProvider`/`Sidebar`/`SidebarMenuButton` w/ `tooltip` prop for collapsed-rail labels; footer slot repurposed for GW+live-state, not a user account | `lucide-react`, `@radix-ui/react-slot`, `class-variance-authority` | **KEEP (approved)** |
| Dashboard with Collapsible Sidebar | https://21st.dev/@uniquesonu/components/dashboard-with-collapsible-sidebar | Full shell layout reference | Layout guide only | Confirms sidebar+topbar+content composition; not installed itself | — | REFERENCE ONLY |
| Dashboard Sidebar (dual-theme) | https://21st.dev/@arunjdass/components/dashboard-sidebar | Collapsed-rail confirmation | — | Same underlying shadcn pattern as primary pick | shadcn stack | REFERENCE ONLY |
| Sidebar Nav Group | https://21st.dev/@felipemenezes098/components/collapsible-05 | Grouped/nested nav sections | Not needed — our 7 destinations are flat | — | — | REJECTED (no nesting need) |

### B2 — Command / Decision Composition

| Component | 21st URL | Purpose | FPL Agent destination | Integration notes | Dependencies | Decision |
|---|---|---|---|---|---|---|
| **Performance Benchmark Card** | https://21st.dev/@kavikatiyar/components/performance-benchmark-card | Headline metric + benchmark marker + ranked competitor list + graded scale bar | Command's alternative-path comparison AND captain matchup; Football's Model vs Market panel | Handoff: takes arbitrary `{title, value, delta, benchmarkLabel, benchmarkValue, competitors: [{icon,label,value}], scaleBands}` — reusable as-is for "leader vs ranked alternatives against a benchmark," which is exactly `sd['paths']`'s own shape | framer-motion | **ADAPT — high priority** |
| Stat Card (compact KPI + trend) | https://21st.dev/@felipemenezes098/components/card-05 | Small metric tile w/ icon + trend badge | TRANSFER/CHIP EDGE, CAPTAIN EDGE, OPTIONALITY row; Plan's by-horizon row | Handoff: `{icon, label, value, delta, deltaDirection}` props | none beyond Tailwind | **ADAPT** |
| **Badge Delta** | https://21st.dev/@serafimcloud/components/badge-delta | Auto-colored +/− pill (Tremor-inspired) | Every real delta number across Command/Plan/Football/Scout | Handoff: `<BadgeDelta value={n} />`, sign-based color, no extra config needed | shadcn/ui base | **ADAPT — cross-cutting atom** |
| Advanced Stats (animated area + KPI) | https://21st.dev/@uilayout.contact/components/advanced-stats | Full analytics-hero layout | KPI-card layout reference only | Explicitly drop its scroll-triggered load animation — Phase 8.0 already removed this exact anti-pattern once | framer-motion | REFERENCE ONLY (layout, not motion) |
| **Status** | https://21st.dev/@haydenbleasel/components/status (Kibo UI) / https://21st.dev/@diceui/components/status | Pulsing-dot pill, semantic color variants | Live-state dot, RECOMPUTING/STALE/CURRENT decision badge, source-health chips | Handoff: `<Status variant="online|offline|degraded">` style enum, dot + label | shadcn/ui base | **ADAPT — cross-cutting atom** |
| Financial Dashboard | https://21st.dev/@ravikatiyar162/components/financial-dashboard | Command-bar + quick-actions + activity-list hub layout | Reference for the Interactive Logs Table's row styling (colored initial-avatar + title + timestamp + amount) | Its "Transfer/Pay/Invest" quick actions don't map (this app is recommend-only, no write actions) — take the activity-row visual only | framer-motion | REFERENCE ONLY (activity-row styling) |

### B3 — Player Comparison (new gap area)

| Component | 21st URL | Purpose | FPL Agent destination | Integration notes | Dependencies | Decision |
|---|---|---|---|---|---|---|
| **Radar Chart** (Intent UI) | https://21st.dev/@intentui/components/radar-chart | Multi-axis attribute shape, filled polygon | My Team's player inspector; Scout's player-vs-player; Football's team attack/defence hover | Handoff: `data: [{axis, value}]`, built on `recharts` | `recharts` | **ADAPT — new capability** |
| Radar Chart (alt) | https://21st.dev/@LegionWebDev/components/radar-chart | Same pattern, alt implementation | Fallback if Intent UI's own styling doesn't fit our tokens as cleanly | — | recharts | REFERENCE (fallback) |
| Us Vs Them Comparison | https://21st.dev/@7ovr/components/comparison-2 | Two-column side-by-side card comparison | Row-pair LAYOUT reference for Player A vs Player B (same stat row, two values, better one highlighted) | Its content (marketing checklist/CTA) is not reused — only the two-column row-pair structure | — | REFERENCE ONLY (layout) |
| Feature Comparison Table | https://21st.dev/@7ovr/components/comparison-3 | 3-column grouped comparison table | Considered for a 3-way (current captain / alternative / 2nd alternative) comparison | Weaker fit than the Performance Benchmark Card's leader+ranked-list shape for our real 1-leader-vs-N-alternatives data | — | REJECTED (B2's pick covers this better) |

**Player A vs B, concretely**: built by composing two pieces already picked —
a **Sheet** for each player (or a shared side-by-side Sheet variant showing
both), each with its own **Radar Chart**, and a row-pair table underneath
(price/xP/form/fixture/ownership, referencing Us-Vs-Them's row layout) with
the better value in each row given a **Badge Delta**-style highlight. No new
component needed beyond what's already picked — this is a composition, not a
missing primitive.

### B4 — Command Palette (deepened)

| Component | 21st URL | Purpose | FPL Agent destination | Integration notes | Dependencies | Decision |
|---|---|---|---|---|---|---|
| **Command Palette** (interior.dev) | https://21st.dev/@ddoemonn/components/command-palette | ⌘K palette, fuzzy search, arrow-key nav, animated overlay | Global — jump to any screen, any player, or a quick action | Handoff (real code read): `CommandItem = {id, label, hint?, keywords?, shortcut?}`, `<CommandPalette open items autoFocus onDismiss onSelect placeholder />` — items list would be generated from the 7 screen names + every real player name (already available via the players payload) | `motion` (Framer Motion / Motion One) — single dependency, lightweight | **ADAPT** |
| Command Palette (raycast-inspired) | https://21st.dev/@rafa-porto/components/command-palette | Global search across content types | Alt reference if multi-source grouping (players/screens/actions as separate sections) is wanted | Heavier feature set than we need day one | — | REFERENCE (fallback if grouping needed) |
| Omni Command Palette | https://21st.dev/@lovesickfromthe6ix/components/omni-command-palette | Async multi-source fuzzy search | Same use case, async-source variant | Our data is local/already-fetched — async sourcing is unneeded complexity | — | REJECTED (over-engineered for local data) |

Scheduled **last** (Stage 10) per the Migration Plan — a net-new capability,
not required for parity with the current dashboard.

### B5 — Advanced Filtering (new gap area)

| Component | 21st URL | Purpose | FPL Agent destination | Integration notes | Dependencies | Decision |
|---|---|---|---|---|---|---|
| **Dual Range Slider** | https://21st.dev/@arihantcodes_1f7b8c4d/components/dual-range-slider | Two-handle min/max range | Scout price filter (£4.0m–£15.0m) | Handoff: standard Radix dual-thumb slider, `min`/`max`/`value: [number, number]` | `@radix-ui/react-slider` | **ADOPT** |
| Combobox | https://21st.dev/@shugar/components/combobox | Filtered searchable select | Scout/Command Palette player-name autocomplete | Handoff: filters a list client-side against a query string — our player list (~650 rows) is small enough for pure client-side filtering, no server-side search needed | `cmdk` (or shared with Command Palette's own fuzzy-match) | **ADOPT** |
| Table with Filters | https://21st.dev/@felipemenezes098/components/table-12 | Search input + status-column dropdown over a table | Confirms **TanStack Table** as the real underlying library worth adopting for Scout | Most of the serious table components researched (Resizable Table, Expanding Sub-Rows, HeroUI Table) are built on TanStack Table — adopt it as the foundation, not just this one demo | `@tanstack/react-table` | **ADOPT (as foundation library)** |
| Toolbar (cnippet-dev / HeroUI) | https://21st.dev/@cnippet-dev/components/cnippet-toolbar | Grouped, keyboard-navigable control bar | Scout's filter-bar container (search+segmented-control+slider+sort together) | Handoff: a `role="toolbar"` wrapper with arrow-key roving focus across its children — accessibility upgrade over a plain flex div | Base UI / Radix | **ADAPT** |
| Filter Grid | https://21st.dev/@ddoemonn/components/filter-grid | Animated segmented-chip filtering with live count | Football's category filter chips (Creation/Goal Threat/Set Pieces/Minutes) | Handoff: chips toggle visibility with a layout animation; shows a live filtered-count | `motion` | **ADAPT** |
| Multiple Select | https://21st.dev/@geekles007/components/multiple-select | Multi-value select | Considered for a multi-team filter in Football; not required for Scout's single-position filter (Segmented Control already covers exclusive choice) | — | — | REFERENCE (only if a multi-team filter is later requested) |

### B6 — Dense Data Workspace (new gap area)

| Component | 21st URL | Purpose | FPL Agent destination | Integration notes | Dependencies | Decision |
|---|---|---|---|---|---|---|
| **Interactive Logs Table** | https://21st.dev/@moumensoliman/components/interactive-logs-table-shadcnui | Observability log rows: severity pill, timestamp, service, message, status, latency, expandable | Advanced's System Health / source-status / readiness checks; Decision Audit trace rows | Handoff (confirmed via screenshot): Info/Warning/Error colored pills, chevron-expand per row, live search+filter header — near-exact match for "OK/DEGRADED/FAIL source checks with a detail row" | shadcn/ui table + Radix Collapsible | **ADOPT — high priority for Advanced's identity** |
| **Records Table** | https://21st.dev/@theshanelevine/components/records-table | Sticky first column, colored tag chips, row selection, footer calculation row | Football's Team State (20 rows), Advanced's Points Changes/Player Odds, Scout's Price Changes History | Confirmed via screenshot: sticky `Company` column stays visible on horizontal scroll — directly solves Team State's own crest+name-should-stay-visible need | TanStack Table | **ADOPT** |
| **Resizable Table** | https://21st.dev/@isaiahbjork/components/resizable-table | User-resizable columns | Scout's dense player table, Advanced's diagnostic tables | Power-user affordance; low priority vs the row-shape work above, real but not required for parity | TanStack Table | ADAPT (low priority, nice-to-have) |
| **Expanding Sub-Rows Table** | https://21st.dev/@felipemenezes098/components/table-19 | Parent row expands to reveal nested children | Opportunity Board's "N more candidates" per category | Strictly nicer version of the existing `<details>`-nested-table reveal — same real interaction, better mechanism | TanStack Table | **ADOPT** |
| Data Grid Table | https://21st.dev/@sean0205/components/data-grid-table | Generic dense grid | — | Weaker/less-specific than the picks above | — | REJECTED |
| Interactive Grid | https://21st.dev/@designali-in/components/interactive-grid | Generic hover-interactive grid | — | Not table-shaped; doesn't fit our tabular data | — | REJECTED |

### B7 — Football / Match Intelligence

(Carried over from round 1, unchanged findings — see full detail below in Part C.)

| Component | 21st URL | Decision |
|---|---|---|
| Radar Chart | https://21st.dev/@intentui/components/radar-chart | ADAPT (see B3) |
| Area/Bar Chart (reaviz, LegionWebDev) | https://21st.dev/@reaviz/components/area-chart-2 , https://21st.dev/@LegionWebDev/components/bar-chart | REFERENCE ONLY (visual treatment; ApexCharts stays the library, see Migration Plan) |
| Prediction Market Card | https://21st.dev/@isaiahbjork/components/prediction-market-card | ADAPT (probability-bar visual only, no betting framing) |
| Activity Feed | https://21st.dev/@felipemenezes098/components/comment-thread-3 | ADAPT (Live event feed, Football signal feed styling reference) |

### B8 — Player / Inspector / Drawer

| Component | 21st URL | Decision |
|---|---|---|
| Sheet — Scrollable Content | https://21st.dev/@shadcnspace/components/sheet-02 | **ADOPT** (player inspector) |
| Sheet — Different Directions | https://21st.dev/@shadcnspace/components/sheet-01 | REFERENCE (edge-direction options) |
| Drawer (swipe + snap points) | https://21st.dev/@coss.com/components/drawer | REJECTED (mobile-oriented; project stays desktop-first) |
| Hover Card | https://21st.dev/@shadcn/components/hover-card | **ADOPT** (dense-table inline preview, My Team weak-link preview) |

### B9 — Motion & Micro-interactions (new — answers "what's cooler here")

The dashboard explicitly REMOVED a load-triggered fade/slide animation in
Phase 8.0 ("animates because premium dashboards animate" anti-pattern). That
lesson holds: nothing below fires on page load. Every pick here is
**event-driven** — it animates because a real value changed (a live score, a
freshly-computed decision, a user interaction) — which is a genuinely
different, justified case, and closer to how actual broadcast graphics work
(a scoreboard ticks up when a goal is scored, not on a timer).

| Component | 21st URL | Purpose | FPL Agent destination | Integration notes | Dependencies | Decision |
|---|---|---|---|---|---|---|
| **Count Up** | https://21st.dev/@unlumen/components/count-up | Number springs to a new target value, per-digit slide/blur/fade | Live rank/points ticking as SSE pushes land; Command/Plan headline numbers animating when a genuinely new decision payload arrives | Handoff (real code read): `<CountUp to={n} from={prev} direction="up|down" separator="," digitEffect="slide" />` — trigger `to` off real prop changes, never a mount-only timer | none beyond React state | **ADOPT** |
| Upstash Counter | https://21st.dev/@elements-/components/upstash-counter | Similar count-up, compact-number formatting (1.2k style) | Alt if compact formatting (e.g. "1.6M" rank) is wanted over full separators | — | — | REFERENCE (formatting alt) |
| **Toast Notification** (framecn) | https://21st.dev/@framecn/components/toast-notification | Springs in, holds, slides out; success/error/warning variants | A real new SSE event landing while the tab is backgrounded (e.g. a goal involving a squad player, a decision recompute completing) | Handoff: spring-in/hold/slide-out timing already tuned; wire its `onDismiss` to real event acknowledgement, never a fabricated "success" toast for a no-op | `motion` | **ADOPT** |
| Progress Bar (ddoemonn) | https://21st.dev/@ddoemonn/components/progress-bar | Animated linear fill + indeterminate shimmer | A real loading state while an `/api/<screen>` fetch resolves (replaces a blank flash) | Indeterminate variant only while genuinely waiting on a real fetch — never a fake progress percentage | — | **ADOPT** (loading state only) |
| Animated Circular Progress Bar | https://21st.dev/@dillionverma/components/animated-circular-progress-bar | Circular gauge with percentage | Considered for a confidence/robustness radial (e.g. decision confidence %) | Real candidate but redundant with the existing ROBUSTNESS/CREDIBILITY text treatment already established in Phase 8.0 — would need a genuine visual-hierarchy reason to add a second confidence encoding | — | REFERENCE (only if confidence becomes a headline metric) |
| **Blur Fade** (Magic UI / dillionverma) | https://21st.dev/@dillionverma/components/blur-fade | Smooth fade+blur mount/unmount | New content arriving via SSE push (a new row appearing in a live feed), NOT page/screen load | Explicitly scoped: trigger on `key` change for genuinely new real data, never on initial render | `motion` | **ADOPT (scoped to real data arrival only)** |
| Pulse Dot | https://21st.dev/@loading-ui/components/pulse-dot | Clean scale+fade pulsing dot | Live-state indicator (replaces the current CSS-only pulse, same visual idea, componentized) | Direct swap for the existing `.topbar-freshness-dot-live`/`.system-live-dot` pulse animation | — | ADAPT (parity upgrade, low priority) |
| Accordion (ddoemonn, spring) | https://21st.dev/@ddoemonn/components/accordion | Spring-animated expand/collapse, keyboard nav | Advanced's module disclosures, Opportunity Board's "more" reveal | Real upgrade over a native `<details>` marker rotation IF the spring feel is judged worth the extra JS — Advanced's own native-`<details>` choice (see Part A) already leans toward keeping this zero-JS; use this instead only where the interaction is frequent enough to notice the polish (Opportunity Board reveal, not every Advanced module) | `motion` | ADAPT (selective use) |

**What was explicitly searched and rejected as decoration**: Spotlight /
SpotlightBackground (gradient-blob hero backgrounds), generic marketing Hero
sections with "Introducing Sparkles"-style copy reveals, 8-bit/retro-pixel
timeline and stats styling. None of these are tied to a real state change —
they animate because the component always does, which is exactly the pattern
this project's own Phase 8.0 already identified and removed once. Not
reintroducing it here just because the catalogue has flashier options
available.

---

## PART C — Carried Over From Round 1 (unchanged conclusions)

### Rejected categories (searched, nothing adopted)
- **Football/sports-specific components** (formation, pitch, scoreboard) — no
  sports-domain component exists on 21st.dev; searched directly, confirmed
  empty. My Team's pitch and Live's match block stay hand-built.
- **Calendar/scheduling components** — every result was a generic
  appointment-booking calendar. Football's fixture matrix stays hand-built
  from real fixture-difficulty data.
- **8-bit/retro-styled components** — wrong visual identity for "official FPL
  + FotMob + broadcast graphics."
- **Glassmorphism/spotlight-gradient heroes** — decorative, not tied to real
  state; rejected per Part 5's own standard.

### Charts
ApexCharts (already vendored, already has a real, audited chart-type↔question
mapping in `.claude/skills/fpl-visualization/`) has an official
`react-apexcharts` wrapper. **No new chart library** — reuse it, including for
the new radar-chart use case (`type: 'radar'` is native to ApexCharts too;
Intent UI's `recharts`-based radar chart in B3 is the fallback if ApexCharts'
own radar styling doesn't hit the mark, decided during implementation, not
here).

---

## Summary — Decisions by Screen

| Screen | Adopt | Adapt | Reference only | Rejected |
|---|---|---|---|---|
| Shell | shadcn Sidebar | — | Collapsible-sidebar dashboard, dual-theme shell | Sidebar Nav Group (no nesting need) |
| Command | — | Performance Benchmark Card, Stat Card, Badge Delta, Status | Advanced Stats (layout only), Financial Dashboard (activity-row styling) | — |
| Player Comparison | — | Radar Chart | Us Vs Them (row-pair layout), Radar Chart alt (fallback) | Feature Comparison Table |
| Plan | Timeline Rail | Modern Timeline, Badge Delta | Agent Plan, Order Tracking (status icons), Aceternity Timeline | Roadmap Card |
| Command Palette | — | Command Palette (interior.dev) | Raycast-style palette (fallback) | Omni Command Palette (over-engineered) |
| Filtering | Dual Range Slider, Combobox, TanStack Table | Toolbar, Filter Grid | Multiple Select | — |
| Dense tables | Interactive Logs Table, Records Table, Expanding Sub-Rows | Resizable Table | — | Data Grid Table, Interactive Grid |
| Scout | Financial Markets Table, Segmented Control | Ticker | Market Watchlist, Market Snapshot | — |
| Football | — | Radar Chart, Prediction Market Card (probability bar only), Activity Feed | Area/Bar Chart | pitch/formation (none exist) |
| My Team | Sheet, Hover Card | Radar Chart | — | swipeable Drawer (mobile-only) |
| Advanced | Interactive Logs Table, Records Table | — | System Monitor | — |
| Live | — | Ticker, Status, Activity Feed, Count Up | — | live-score components (none fit) |
| Motion | Count Up, Toast Notification, Blur Fade (scoped), Progress Bar (loading only) | Pulse Dot, Accordion (selective) | Upstash Counter, Circular Progress | Spotlight/gradient heroes, 8-bit styling |

See `docs/FRONTEND_MIGRATION_PLAN.md` for the Python↔React data boundary,
staged rollout, and dependency plan (§Component/dependency plan will be added
there once this composition is confirmed).
