---
name: FPL Agent
description: A personal FPL decision terminal built as a live football broadcast package - a match-graphics truck, not a SaaS dashboard.
colors:
  canvas-void: "#0A0E14"
  surface-panel: "#12171F"
  surface-raised: "#1A2029"
  pitch-green: "#1FCE6B"
  pitch-green-deep: "#12A552"
  broadcast-gold: "#F0A93E"
  broadcast-blue: "#2D6CDF"
  alert-red: "#E3452F"
  text-primary: "#F5F3EE"
  text-muted: "#9099A8"
  text-faint: "#5B6472"
  divider: "#232B36"
typography:
  display:
    fontFamily: "Oswald, 'Arial Narrow', sans-serif"
    fontSize: "clamp(3.5rem, 8vw, 7rem)"
    fontWeight: 700
    lineHeight: 0.92
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Oswald, 'Arial Narrow', sans-serif"
    fontSize: "1.75rem"
    fontWeight: 600
    lineHeight: 1.05
    letterSpacing: "0.01em"
  label:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0.12em"
  body:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  data:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "normal"
    fontFeature: "tnum"
  system:
    fontFamily: "IBM Plex Mono, ui-monospace, monospace"
    fontSize: "0.6875rem"
    fontWeight: 400
    letterSpacing: "0.1em"
rounded:
  none: "0px"
  sm: "2px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "32px"
  xl: "64px"
motion:
  ease: "cubic-bezier(0.16, 1, 0.3, 1)"
  dataIn: "320ms"
  barDraw: "620ms"
  livePulse: "1600ms"
components:
  verdict-block:
    backgroundColor: "{colors.pitch-green}"
    textColor: "{colors.canvas-void}"
    rounded: "{rounded.none}"
    padding: "32px 40px"
  tag-block:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.none}"
    padding: "6px 12px"
  fdr-chip:
    backgroundColor: "{colors.pitch-green}"
    textColor: "{colors.canvas-void}"
    rounded: "{rounded.none}"
    padding: "1px 4px"
  live-pill:
    backgroundColor: "{colors.alert-red}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.pill}"
    padding: "3px 10px"
---

# Design System: FPL Agent

> **Status.** This file is the authority for the React frontend
> (`frontend/`). Where this document and the code disagree, the code is the
> bug. It was rewritten end-to-end on 2026-09-09 after drifting badly out of
> date — it still claimed monospace was unused while fifteen components used
> it, still described `clip-path` as a core device with one real call site,
> and said nothing at all about charts, motion, loading states, or the seven
> screens' distinct identities. It now describes what is actually built.

---

## 1. North star

**A football broadcast package, run by one person, for one squad.**

Every screen should feel like the graphics truck at a match: the scoreboard
bug, the half-time stat wipe, the fixture ticker crawling under a build-up
show, the analyst's touchscreen. Flat saturated colour blocks instead of
cards. Condensed oversized numerals instead of KPI tiles. Thick rules
instead of borders. Real pitches, real kits, real crests, real opponents.

Two hard rejections, both of which this project has already built once and
thrown away:

1. **The generic dark SaaS dashboard.** Sidebar, page title, a grid of
   rounded shadowed cards, one card per fact, every fact the same size.
2. **The AI-slop aesthetic.** Cyan/purple neon, glassmorphism, aurora
   blobs, gradient text, glow rings, monospace worn as a costume.

**The test.** Strip the FPL data out and drop in arbitrary business metrics.
If the page still works, the design has failed. There should be shapes on
these screens that only make sense because this is football: a formation, a
pitch, a shot map, a fixture run coloured by difficulty, an armband, a
scoreline, a momentum band, a substitution.

**Density is not the enemy of boldness.** The single user reads dense data
fluently and wants the verdict fast. A scoreboard bug carries score, clock
and possession in one confident glance; this system holds drama and density
at once rather than trading one for the other.

---

## 2. Colour

Flat and saturated. Colour groups information; it is never an accent
sprinkled on a neutral field, and it is never decorative.

| Role | Token | Hex | Meaning |
|---|---|---|---|
| Verdict | `pitch-green` | `#1FCE6B` | the recommended action, positive delta, healthy, easy fixture |
| Standout | `broadcast-gold` | `#F0A93E` | captaincy, premium pick, provisional/watch, "my squad" marker |
| Neutral analytical | `broadcast-blue` | `#2D6CDF` | informational, the away side, non-verdict data |
| Danger | `alert-red` | `#E3452F` | risk, fragile, unavailable, hard fixture, live |
| Canvas | `void` | `#0A0E14` | base; cool near-black, never `#000` |
| Surface | `panel` | `#12171F` | first layer — section bands |
| Surface | `raised` | `#1A2029` | second layer — tags, hover, nested cells |
| Rule | `divider` | `#232B36` | separation, in place of borders and shadows |
| Ink | `text` / `muted` / `faint` | `#F5F3EE` / `#9099A8` / `#5B6472` | warm off-white, never `#fff` |

**Semantic discipline.** A colour means one thing per context and keeps
meaning across screens. Green is the recommendation on Command, the home
side in a match, and an easy fixture on a ticker — in all three it is "the
good direction." Gold is never used to mean danger; red is never used for
emphasis.

**One category owns a section.** A chip-type verdict is blue throughout its
band, not blue-plus-a-random-second-accent.

---

## 3. Typography

Four registers. Each has a job; using one outside its job is the drift this
system watches for.

- **Display** — Oswald 700, condensed, `clamp(3.5rem, 8vw, 7rem)`.
  The single hero verdict per screen. `PLAY FREE HIT`. `ACT`. `FRAGILE`. A
  scoreline. Nothing else earns this size.
- **Headline** — Oswald 600–700, 1.1–2.5rem. Player names on a face-off,
  section verdicts, a team's short name on a scoreline, formation strings.
- **Label** — IBM Plex Sans 700, 9–11px, `0.10–0.16em` tracking, uppercase.
  The small caption above every number and beside every rule. This is the
  most-used register in the app and it is what makes a band read as a
  broadcast graphic rather than a form.
- **Body** — IBM Plex Sans 400, 0.9375rem, capped ~70ch. Reasoning,
  evidence, disclosure text.
- **Data** — IBM Plex Sans 600 with `font-feature-settings: "tnum"` (the
  `.tabular` utility). **Every number in the app.** Tabular figures on the
  real body family is a typographic decision; a monospace family would be a
  costume.

**Monospace has one job, and it is a real one.** `font-mono` (IBM Plex Mono)
is reserved for *machine speech*: mastheads, timestamps, CLI command names,
snapshot ages, sync cadence, system identifiers. It is the voice of the
system talking about itself. It never carries football content and never
carries a projection. Earlier versions of this document claimed monospace
was unused while the app used it in fifteen places — the rule above is the
one the code actually follows, and it is the right one.

---

## 4. Elevation and separation

**Flat. No shadows anywhere.** Not on cards, not on modals, not under
shirts. Layering is:

1. surface colour (`void` → `panel` → `raised`),
2. a thick rule (`border-y-2 border-divider`) between full-width bands,
3. a `gap-px` grid over a `bg-divider` parent, which draws hairline rules
   between cells with no borders at all,
4. a left accent rule (`border-l-4`) to mark a row's category or severity.

**The `gap-px` grid has one failure mode, and it is now a rule:** an empty
grid track renders as a solid grey block. Column counts must follow the
number of children that genuinely have data. This shipped as a visible
defect twice before it was written down.

**`clip-path` is used exactly once**, on `.verdict-block` — the angled cut
under the hero verdict. It is a signature, not a system: one screen, one
element. Do not add a second.

---

## 5. Football language

This is the section that separates this app from a dashboard. These are
the shapes that only exist because the subject is football, and they are
required, not decorative.

### The pitch
`.pitch-surface` (mowed stripes) + `<PitchMarkings />` (real geometry at
real proportions: 68m × 105m, 40.32×16.5 penalty areas, 18.32×5.5 six-yard
boxes, 9.15m centre circle and D, 1m corner arcs, goal frames). Portrait,
because a squad reads goalkeeper-first. Used by My Team's squad, Command's
action XI, and Scout's template team.

### The formation
A squad is laid out **GK → DEF → MID → FWD in centred rows**, with the
formation string (`3-5-2`) derived from the real position counts.
**Never sort a starting XI by projected points.** That was shipped once: it
opened with a defender and put the goalkeeper eleventh, and it read as a
leaderboard of eleven strangers. If position data cannot support a
legitimate shape, fall back to a flat list and *say so* — a fabricated
4-4-2 is a lie about the team.

### The fixture chip
`<NextFixture>` / `<FixtureRun>` — opponent crest, opponent short name,
`H`/`A`, filled with the real FPL 1-5 FDR colour. One shared scale
(`lib/fdr.ts`) so a fixture can never read "easy" on one screen and neutral
on another. This appears under every player on every pitch, in the scouting
table, and in the detail panel. It is the single highest-value piece of
football texture in the app: a squad tile without an opponent on it is a
spreadsheet row.

### Kit and crest
Real shirts (`shirtUrl`) at real scale, real crests (`crestUrl`) ringed
against the canvas. **Scale is meaning**: a large shirt is a hero, a 16px
crest is an identifier. Never a tiny decorative shirt inside every card, and
never stock football photography.

### The armband
`C` on gold, `V` on raised. On the tile, top-right, always.

### The scoreline
Home short name, crest, `2–1`, crest, away short name — the number
dominant, a live minute or `HT` under it with a pulsing red dot only when
genuinely live.

### The contest
Two sides of one quantity drawn as **opposed bars off a shared centre or a
shared scale** — possession, xG, shots in a match; xGA against xG across
the league. A contest is one shape, not two numbers to compare by hand.

### The league table
The most basic object in the sport, and the one this app went longest
without. Computed from real results, ordered the real way (points → goal
difference → goals for). Position gutter carries the real zone marks (top
four, relegation). Form is W/D/L cells, most recent first, and genuinely
short when a club has played twice. A club the user owns is marked, never
re-sorted.

### The fixture calendar
A fixture has exactly two states: a result, or a kickoff time. Never both,
never a placeholder score. Grouped by real matchday, the way a fixture list
is published. Kickoff times are stored and shipped as real UTC and rendered
in the viewer's local time — the browser is the only place that timezone is
actually known.

### Everything is a door
A crest, a club name and a player name are links, everywhere they appear. A
football tool lets you follow a thread: table → club → squad → player → match
log → match report → the other club. Detail routes (`/club/:id`,
`/player/:id`, `/match/:id`) have no nav entry — they are reached by
clicking — but they are still real destinations and the header must name them
rather than falling through to the first nav item.

### The ticker
A run of fixtures as flat FDR cells, ordered by schedule pressure (the mean
of the difficulties drawn in that row's own cells — arithmetic over what the
reader can see, labelled `Avg FDR`, never presented as a model output).

### The shot map
Real FotMob x/y on a two-half pitch, away side mirrored `100 - x`, values
clamped to 0-100, radius scaled to real xG, filled only for a goal.

### The momentum band
FotMob's raw -100..100, home above the line, away below. No smoothing, no
interpolation across minutes the feed never sent.

---

## 5A. The season clock — the app knows what time it is

**This is the spine of the product, not a feature.** FPL is a clock: build-up
→ deadline → lock → live → settle → review, every week, all season. Until
2026-09-09 this interface had no clock at all. It rendered identically at 3am
on a Tuesday and with six matches live and your captain on the pitch — and
worse, it showed the same giant `PLAY FREE HIT` instruction in both, telling
the user to do something that was, at that moment, impossible.

Two real backend values drive everything, both already on the fast-poll
channel: `gw.state` (the real `models/gw_lifecycle.py` state machine) and
`gw.next_deadline_time` (FPL's own UTC deadline). `lib/clock.ts` turns them
into a phase. No phase is guessed from the wall clock alone — the lifecycle
state always wins and the countdown only refines it. A live match overrides
everything, because football being played now outranks any cached state.

| Phase | When | Colour | Can the squad change? |
|---|---|---|---|
| `BUILD_UP` | PRE_DEADLINE, >24h | raised | yes |
| `IMMINENT` | PRE_DEADLINE, <24h | gold | yes |
| `FINAL_CALL` | PRE_DEADLINE, <3h | red | yes — barely |
| `LOCKED` | deadline passed, no football yet | raised | no |
| `LIVE` | a match is genuinely in progress | red, pulsing | no |
| `SETTLING` | NEXT_GW_ANALYSIS | gold | no |
| `REVIEW` | READY_FOR_NEXT_DEADLINE | green | yes |

### The Matchday Bar
A persistent broadcast strip under the header, on **every** screen: the phase
block, the ticking countdown in the Display register, one line saying what the
phase means for what you can do, and — only when football is genuinely on —
live scorelines with crests, how many of your players are on the pitch, and
their goals and assists. It rides the existing `useLiveMeta` poll, so it costs
no extra fetch. The countdown ticks locally: a countdown computed server-side
is stale the instant it is serialized.

### Phase drives composition
**The section order is the product.** Command holds one set of sections and
two orders:

- **Actionable** (`BUILD_UP` / `IMMINENT` / `FINAL_CALL` / `REVIEW`) answers
  *"what should I do?"* — decision → the XI it produces → horizon → captaincy
  → path → evidence → confidence.
- **Locked / live** answers *"what have I got?"* — the squad leads, the
  captain (who is on the pitch right now) follows, and the decision drops to
  the bottom, where it belongs: a record of what was chosen, not an
  instruction. A banner states this outright.

Same data, same components, re-ranked by what the user can actually act on.
Any future screen that shows an instruction must ask the phase whether that
instruction is still possible.

---

## 6. Motion

Three motions. Only three. Every one marks a real event.

1. **Data arrival** (`.data-in`, 320ms). A screen's content replaces its
   skeleton exactly once, when the real payload lands — so a mount animation
   here *is* a data-arrival animation. Poll refreshes update in place and
   never re-trigger it. `.data-in-seq` staggers a band's children by 45ms,
   capped at six steps.
2. **Magnitude** (`.bar-draw`, 620ms). Every comparison bar encodes a
   quantity as a length; drawing that length makes the quantity the thing
   that moves. `transform: scaleX`, never `width` — no layout is
   recalculated. `.bar-draw-right` for a bar that grows leftward.
3. **Live** (`.animate-pulse-live`, 1600ms). The only continuous animation
   in the system, and it is a signal: it runs *only* where something is
   genuinely live right now.

Everything shares one easing, `--ease-broadcast: cubic-bezier(0.16, 1, 0.3,
1)` — fast start, hard settle, the way a scoreboard graphic snaps into place.

**Every one of them is disabled under `prefers-reduced-motion: reduce`.**
That media query is not optional and is not per-component.

**Forbidden:** floating, breathing, endless pulsing on non-live elements,
glowing borders, particles, parallax, spring bounces, hover lifts,
page-load flourishes, staggered entrance on a poll refresh, and any
animation whose only justification is that dashboards animate.

---

## 7. Numbers

- Every number uses `.tabular`. Columns of figures must align.
- `<MetricNumber>` animates a value that *changes while on screen* — a live
  rank, a live points total. It is a data-arrival cue, never a page-load
  timer.
- A number that is genuinely unknown renders as `—`. **Never `0`, never a
  default, never an average standing in for a missing value.** A measured
  zero must be stated as a measured zero in words ("the detector ran and
  found nothing"), because a bare `0` and an absent value look identical
  and mean opposite things.
- Units and horizons are stated: `xP`, `pts over 8 GW`, `avg FDR`,
  `raw implied, not devigged`. A naked number with no unit is a defect.

---

## 8. Charts

All charts go through `lib/chartTheme.ts::baseChart()`. A per-chart override
is then a deliberate act rather than an accident of copy-paste. Before this
existed, four charts each re-declared their own grid colour, tooltip theme
and stroke width, and drifted — one grew a two-stop gradient fill this
system forbids, another rendered fractional gameweek ticks.

Rules:

- **Every chart answers a stated question.** If you cannot write the
  question above it, delete the chart. Prefer one strong visual with a clear
  explanation over four generic ones.
- Flat fills only. `flatAreaFill()` is one colour at one low opacity — the
  line stays the information, the wash stays context. No multi-stop
  gradients, no glow, no shadows.
- Square corners on bars (`borderRadius: 0`).
- Semantic palette only (`CHART_COLORS`), never a decorative ramp.
- **Gameweeks are integers.** Every gameweek axis formats through
  `gwAxisLabels`. There is no GW 6.8.
- Rank axes are reversed and abbreviated (`rankAxisLabels`) — lower is
  better, and an unreversed axis draws a real climb as a fall.
- Direct labels, not legends. `legend: show:false` is the default; if a
  chart has more than one series, label the series next to the title with a
  coloured rule.
- Animate once on arrival; never re-animate on a poll tick.

Charts are the *exception*, not the default. Most quantities in this app are
better as a flat bar, an opposed rule, or a number — a `<Chart>` is for a
real series over time.

---

## 9. Tables

Tables are analytical instruments, not content inside a card.

- No wrapping box. Thick header rule, hairline row rules, dense rows.
- `<th scope>` on headers and row headers; a `<caption class="sr-only">`.
- A state marker in the row gutter (a 1.5px dot, a `border-l-4`), not a
  badge per cell.
- Sticky header when the body scrolls; `overflow-x-auto` on the wrapper so
  the page body never scrolls horizontally.
- Numbers right-aligned and `.tabular`; identity left.
- Row emphasis by background wash (`bg-panel`) and an accent edge, never by
  a per-row border.

---

## 10. Loading, error, empty

`components/shell/ScreenStates.tsx`.

**Skeletons are shaped like the screen they precede.** Command's decision
field, My Team's pitch rows, Plan's gameweek grid, Scout's table beside its
panel, Live's console strip, Advanced's verdict band, Football's ticker.
Skeleton blocks are square-cornered and flat — a rounded skeleton previews a
page that never arrives. A stack of grey rounded rectangles is a promise of
a card grid, and this app renders no card grids.

**Errors say what is unknown.** One shared composition: a left red rule on a
panel, never a full-bleed red banner (a fetch failure is information, not an
alarm). The copy must state that nothing is being served from cache and
nothing is being substituted, and it must not imply the underlying system is
healthy. "Readiness is unknown right now, which is not the same as healthy."

**Empty states explain.** What normally appears here, why it is empty,
whether that is expected, and what would fill it. Live's no-match state
names every part of the match centre that will appear and states that
nothing is simulated in between.

---

## 11. Screen identities

One visual language, seven personalities. Making every screen look the same
is a failure; so is making them look unrelated.

| Screen | Identity | Dominant object |
|---|---|---|
| **Command** | decision terminal | the verdict block + the action XI on a pitch |
| **My Team** | tactical board | the squad on a marked pitch |
| **Plan** | strategy desk | the path × gameweek grid |
| **Matchweek** | the football itself | the league table and the fixture calendar |
| **Club file** | a club, on its own terms | results with xG beside the scoreline |
| **Player file** | one footballer | the per-match log |
| **Match report** | one game | the two-sided timeline |
| **Football** | broadcast desk | the fixture ticker and the change wire |
| **Scout** | scouting workstation | the table beside a persistent detail panel |
| **Advanced** | analyst's workbench | the adversarial audit verdict |
| **Live** | control room | the console strip and the match centre |

Command's narrative order is **not** fixed - see §5A. When the squad can
still change it runs decision → XI → horizon → captaincy → strategy →
evidence → confidence, one argument rather than a stack of panels. Once
the squad is locked or football is live, the XI leads and the decision
recedes to a record.

---

## 12. Honesty rules (these outrank aesthetics)

This system is attached to a recommendation engine. Presentation may never
make a claim the data does not support.

- **Never fabricate.** No placeholder opponent, no invented probability, no
  default price, no filled-in stat. Absent renders as absent.
- **Never imply an action was taken.** The app recommends; it never
  executes, and no button may look like it submits anything.
- **Never label stale data live.** A successful fetch is not a fresh
  snapshot. Freshness comes from the payload's own timestamp.
- **Provisional stays labelled.** Provisional bonus can evaporate. Raw
  bookmaker probability is not devigged. A cached audit can be days older
  than the decision it audits — show its age.
- **Disclose gaps in the UI, not just in a docstring.** If a real
  computation exists but is not ported, say exactly that and name it.
- **One authoritative recommendation.** No panel may show a verdict that
  could contradict Command. A panel answering a *different* question must
  say which question.

---

## 13. Do / Don't

**Do**
- Put a real opponent, crest and FDR next to every player.
- Give the hero verdict the whole Display register and let it dominate.
- Use flat bands and rules to separate; let colour do the grouping.
- Let scale carry importance — the lead evidence item is large, the rest
  compress.
- Keep tables dense and instrument-like.
- Draw a quantity as a length when it is a comparison.
- State the unit and the horizon on every number.

**Don't**
- Add a shadow, glow, gradient fill, gradient text, or glass panel.
- Wrap a table or a chart in a bordered card.
- Sort a starting XI by anything but position.
- Animate anything that is not arriving, measuring, or live.
- Repeat one card treatment for every fact regardless of importance — a
  scoreboard bug never gives a substitution and the final score equal
  weight.
- Use monospace for football content.
- Render `0` where the truth is "unknown".
- Build for mobile. Desktop-first is permanent here: verify at 1440px
  primary, 1080px secondary. Narrow widths must remain usable, never
  optimised.

---

## 14. Component inventory

Shared, in dependency order:

- `components/shell/` — `AppSidebar` (three-section nav rail: Decision /
  Intelligence / Operations), `ContextHeader` (broadcast status strip),
  `Masthead` (per-screen edition line), `ScreenStates` (skeleton primitives
  + `ScreenError`), `CommandPalette`, `MetricNumber`.
- `components/football/` — `PitchMarkings`, `FixtureRun` /
  `NextFixture` / `RunPressure` / `FixtureLine`.
- `components/command/` — `DecisionHero`, `ComparisonGraphic`,
  `PlayerGallery` (the formation), `CaptainFaceOff`, `DecisionHorizon`,
  `StrategyRail`, `EvidenceRail`, `ConfidenceGraphic`.
- `components/live/` — `MatchCentre` (scoreline, opposed stats, momentum
  band, shot map, my players), `BonusDefconRail`.
- `components/advanced/` — `DecisionAudit`.
- `components/shell/MatchdayBar.tsx` — the season clock, on every screen.
- `lib/` — `clock.ts` (the phase machine and countdown), `fdr.ts` (the one
  FDR scale), `chartTheme.ts` (the one chart language), `useFetch.ts`
  (polling: 10s Live, 60s elsewhere), `time.ts`.

Do not create `UniversalCard`, `UniversalPanel`, or
`UniversalDashboardSection`. Compositions here are authored per screen on
purpose; shared components exist for real football and system primitives,
not to avoid writing markup.
