---
name: FPL Agent
description: A personal FPL decision terminal printed as a matchday programme - newsprint, black ink, one vermilion spot colour, stadium-signage type - not a SaaS dashboard.
colors:
  paper-void: "#E9E0CC"
  paper-panel: "#F6F0E2"
  paper-raised: "#E2D7BF"
  ink: "#17130E"
  spot-vermilion: "#FF4614"
  pitch-green: "#0B7D40"
  broadcast-gold: "#B97900"
  broadcast-blue: "#1C3FD1"
  alert-red: "#D82B17"
  text-muted: "#463E32"
  text-faint: "#7D715D"
  divider: "#C7B99C"
typography:
  display:
    fontFamily: "'Big Shoulders Display', Oswald, 'Arial Narrow', sans-serif"
    fontSize: "clamp(3.5rem, 8vw, 7rem)"
    fontWeight: 700
    lineHeight: 0.92
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "'Big Shoulders Display', Oswald, 'Arial Narrow', sans-serif"
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
  sm: "4px"
  md: "8px"
  lg: "14px"
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

**The matchday programme (2026-10-29, replacing the dark broadcast palette).** The graphite canvas with mint, champagne,
azure and coral read, to the one person this is for, as every AI-generated dashboard ("i still dont like the colour,
it still just looks so ai like"). The whole app is now printed: warm newsprint paper, near-black ink, and spot colours
the way a club programme or fanzine uses them. Token names are unchanged so every component followed; their meanings
are unchanged, only the ink.

| Role | Token | Hex | Meaning |
|---|---|---|---|
| Brand spot | `spot` | `#FF4614` | the call (verdict slab), section marks, the active tab and nav number, the ticker label; never a data meaning |
| Good | `pitch-green` | `#0B7D40` | the recommended direction, positive delta, easy fixture, availability |
| Standout | `broadcast-gold` | `#B97900` | captaincy, "my squad", watch |
| Neutral data | `broadcast-blue` | `#1C3FD1` | informational, away side, links |
| Bad | `alert-red` | `#D82B17` | risk, unavailable, hard fixture, live |
| Page | `void` | `#E9E0CC` | newsprint, with a 7px halftone dot and a vermilion wash at the top |
| Surface | `panel` / `paper` | `#F6F0E2` | printed card |
| Surface | `raised` | `#E2D7BF` | tags, nested cells, the bench strip |
| Rule | `divider` | `#C7B99C` | light rules inside a card |
| Ink | `ink` / `text` / `muted` / `faint` | `#17130E` / `#17130E` / `#463E32` / `#7D715D` | card borders, hard shadows, text |

Text on a filled ink, green, blue or red block is `paper`; on gold or vermilion it is `ink`. Graphics that are pictures
in their own right (the dark-turf shot maps, the club-colour photo plates) keep their own colours as inset plates.

**Semantic discipline** is unchanged: green is the good direction everywhere, red the bad, gold never means danger,
and the vermilion spot never carries a data meaning at all.

---

## 3. Typography

**2026-10-29:** display type is **Big Shoulders Display** (500-900, self-hosted in `public/fonts`, latin and latin-ext),
the stadium-signage condensed, set heavy (semibold display text renders at 800, bold at 900 by one rule in `index.css`)
and in capitals for titles. **Instrument Serif italic** is the programme's voice: verdict lines, tab notes, the
sidebar's edition line (`.voice`, `font-serif`). Body and data stay IBM Plex Sans with tabular figures. Oswald remains
only as a fallback. Check `document.fonts` after any change: the 2026-09-08 lesson was that a face named in CSS is not
a face on screen.


Five registers. Each has a job; using one outside its job is the drift this
system watches for.

- **Display** — Big Shoulders Display 900, capitals. The call, poster names (the armband spotlight, the player file),
  the matchday figures. Nothing else earns poster size.
- **Headline** — Big Shoulders Display 800-900, 1.3-2.1rem: section chyrons, tab names, the header screen name,
  numbers in a figure.
- **Voice** — Instrument Serif italic, 15-19px: the one editorial line under something (a verdict, a tab note,
  "next best"). Never a number, never a label.
- **Label** — IBM Plex Sans 500-700, 11-13px. Section captions above a block are tracked small capitals at 11px (one
  rule in `index.css`); other labels sentence case.
- **Body** — IBM Plex Sans 400, 0.9375rem, capped ~70ch. Reasoning,
  evidence, disclosure text.
- **Data** — IBM Plex Sans 600 with `font-feature-settings: "tnum"` (the
  `.tabular` utility). **Every number in the app.** Tabular figures on the
  real body family is a typographic decision; a monospace family would be a
  costume.

**Monospace has one job, and it is a real one.** `font-mono` (IBM Plex Mono)
is reserved for *machine speech*: CLI command names and code in an error or an
empty state. It is no longer used for labels or mastheads. It is the voice of the
system talking about itself. It never carries football content and never
carries a projection. Earlier versions of this document claimed monospace
was unused while the app used it in fifteen places — the rule above is the
one the code actually follows, and it is the right one.

---

## 4. Elevation and separation

**Printed cards (2026-10-29).** Every top-level band (`.screen-frame > * > *`) and every `Panel`/`Disclosure`/
`.slab` is a paper card with a 2px ink border, square corners and a hard 6px ink offset shadow - the shadow of a printed
sticker, not a glow. Inside the frame `rounded-md/lg/xl` are forced to 2px; `rounded-full` (avatars, rings) keeps its
shape. Every band carries its running page number (01, 02...) printed large and faint in its top-right corner (a CSS
counter, behind content; not on collapsed `details`). The sidebar is a solid ink spine with paper text, vermilion
group labels and the active item as a paper slip with a vermilion offset; the header is paper on a 2px ink rule with
the screen name in 2.1rem display capitals.

Layering is:

1. paper colour (`void` -> `panel` -> `raised`),
2. ink border and hard offset shadow between bands,
3. a 1px `divider` rule between rows inside a card,
4. a `gap-px` grid over a `bg-divider` parent for hairline cell rules,
5. a **tone** (`.tone` plus a `border-<colour>` class): a tinted, outlined note in that colour. No side tabs.

**Section titles** are `h2.font-display`: 2.05rem, weight 900, capitals, behind a vermilion parallelogram (`::before`).
**Labels, not capsules:** `Pill` is small capitals behind a slanted colour tick.

**Command** opens on the matchday bar (the call on the vermilion `.verdict-block`, oversized figures, a rotated rubber
stamp for a lineup gain), then the stage (`CommandStage.tsx`: a pinhole-projected printed pitch, upright shirts with
ink name slips, an ink fixture ticker with a vermilion label, the armband spotlight as a club-colour photo plate with a
halftone screen and a poster-sized name with a vermilion offset), then five folder tabs in ink.

**The `gap-px` grid has one failure mode, and it is a rule:** an empty grid
track renders as a solid grey block. Column counts must follow the number of
children that genuinely have data.

**Type sizes.** The floor is 11px for uppercase mono/label text and 12-13px for
everything a person reads; `text-xs` is 13px and `text-sm` 15px in the theme.
The first version ran labels at 9-10px, which was unreadable at a desk.

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

**Headshots (2026-10-16).** Where a *person* is the subject - a transfer, the captain battle, an injury note, a fixture's key players - the official Premier League headshot (`playerPhotoUrl`, keyed by the FPL player `code`, so a transfer cannot leave it stale) is used through `PlayerPhoto`, on a flat `raised` tile, bottom-aligned and cropped, never stretched, falling back to the club shirt when the code or image is missing. The formation and squad tiles keep shirts: position on the pitch is their meaning. Attached to payloads by `monitoring/api/photos.py::attach_photo_codes`.

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

### The replay (2026-10-21)
`components/match/MatchReplay.tsx`. One full pitch in metres (105 x 68, the
viewBox *is* the pitch) with both sides' shots on it: the home side as
recorded, the away side mirrored (`x -> 105 - x`, `y -> 68 - y`) so each side
attacks its own end. Dot area is xG, filled only for a goal, a ring on the
last two minutes' shots. Under it the match's spine: cumulative xG for both
sides, the game state as a band (who led, when), every goal, substitution and
card at its minute, and a cursor that *is* the minute (drag, arrow keys,
Home/End, space, or play at 11 minutes a second). Everything above the cursor
is what had happened by then; nothing is projected. The slider is an
`svg role="slider"`, keyboard-operable, and does not autoplay.

### The deserved-result bar
A single full-width bar of win / draw / loss probabilities from the shots
replayed as independent chances, with a triangle under what actually happened.
Home is green, away blue, the draw is the raised surface. It is the one place
luck is drawn as a distance between a bar and a marker, not as a number.

### Persistence whiskers
`components/football/SignalLedger.tsx`. A diamond for the measured correlation,
a rule for its 90% interval, a gold line at the 0.10 a signal must clear. Green
persistent, gold unclear, red does not carry. A finding that rests on a measured
signal carries its verdict as a small tint chip, never as a confidence colour.

### The style quadrant
`components/football/StyleQuadrant.tsx`. Every club on two measured dimensions
of style (dead balls, counters, volume v quality, where from), one dimension at
a time, the dashed lines the league average. A corner is a way of playing, not a
rank; the corner captions name it.

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

### The header bar
One 56px bar on **every** screen (`ContextHeader`; the separate Matchday Bar
and the per-screen breadcrumb strip were folded into it on 2026-10-24, because
the old stack said "GW8" and "live" three times): page title, how many matches
are on (or "GW8 in progress" when none is), the countdown to the **next
deadline that is still ahead**, live scorelines with crests, data freshness and
Sync. It rides the existing `useLiveMeta` poll, so it costs no extra fetch. The
countdown ticks locally: a countdown computed server-side is stale the instant
it is serialized.

### Phase drives composition
**The section order is the product.** Command holds one set of sections and
two orders:

- **Actionable** (`BUILD_UP` / `IMMINENT` / `FINAL_CALL` / `REVIEW`) answers
  *"what should I do?"* — decision → the XI it produces → horizon → captaincy
  → path → evidence → confidence.
- **Live** no longer demotes the decision. Transfers for the next gameweek
  open the moment a deadline passes, so while matches are on Command still
  leads with the plan for the next one, and a single line above it (points now,
  likely finish, chance of finishing ahead of the average manager) links to
  Live. The old "nothing can be acted on" banner was wrong and is gone.

Any future screen that shows an instruction must ask whether that instruction
is still possible, and for which gameweek.

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
- **One hue, faded.** (Revised 2026-10-25: the flat-fill rule produced charts the
  user called bland.) `areaFade()` is a vertical fade of the series colour, opaque
  at the line and clear at the axis (`reversedAxis` for rank charts, where the line
  sits at the bottom of the area); `barFill()` thins a bar toward its base. Still no
  rainbow ramps, no glow, no drop shadows.
- Bars are rounded at the free end (`borderRadius: 5`, `borderRadiusApplication:
  'end'`); lines end in a round cap and a continuous series is a monotone curve
  (`stepline` for a quantity that jumps, such as points or rank during a
  gameweek). Dashed horizontal grid, no axis border or ticks, a thin dashed hover
  crosshair, tooltips in the app's own panel (`.apexcharts-tooltip` in index.css).
- **End on the number.** `lastPoint(x, y, colour, text)` marks and labels the last
  point of a series; bars carry their value above them.
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
- A state marker in the row gutter (a 1.5px dot or a thin coloured rule beside the rank), not a
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
- **A finding states what it measured, not what it feels like.** Analyst text
  is a number with its context; an adjective that adds nothing is deleted. A
  finding about something measured not to persist says so in the same
  sentence, and its confidence is capped.
- **Every route but Command is its own chunk.** Screens are `React.lazy`
  imports behind one `Suspense` fallback; a heavy library (three.js, leaflet,
  ApexCharts) must load only on the screen that uses it. (three.js is no
  longer a dependency: the podium, season helix, trophy shelf, xG mountains,
  win-probability orb, transfer flip and 3D pitch were all removed as
  decoration that told nothing.)

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
- Add a shadow, glow, gradient text, or glass panel. (A one-hue fade under a chart line or inside a distribution is the exception, section 8.)
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

- `components/ui/kit.tsx` — the shared vocabulary: `Panel` (sentence-case
  title at one size, one-line subtitle, optional right text), `Disclosure`
  (a collapsed panel that still says what is inside), `Pill`, `Fig`,
  `chipName`, `money`. New screens are built from these.
- `components/shell/` — `AppSidebar` (five groups: This week / The league /
  Players / How I am doing / System), `ContextHeader` (the one bar above every
  screen), `Masthead` (a screen's one line of context, or nothing),
  `ScreenStates` (skeleton primitives + `ScreenError`), `CommandPalette`,
  `MetricNumber`.
- `components/football/` — `PitchMarkings`, `FixtureRun` /
  `NextFixture` / `RunPressure` / `FixtureLine`, `SignalLedger`,
  `StyleQuadrant`.
- `components/match/` — `MatchAnalyst` (composition), `MatchReplay`,
  `AnalystPanels` (deserved result, game state, situation mix, substitutions,
  findings).
- `components/command/` — `DecisionSheet` (transfers, armband, lineup side by
  side, account underneath), `SquadPitch` (fixed row spacing, no wrapping),
  `MoveCard`, `EyeTest`, `MarginalValue`, `CaptainLadder`, `DeadlineChecklist`,
  `RoadAhead`, `DeskStrip`, `LiveStrip`; the older `DecisionHero`,
  `PlayerGallery`, `CaptainFaceOff`, `DecisionHorizon`, `StrategyRail`,
  `EvidenceRail`, `ConfidenceGraphic` remain only for the no-week-plan fallback.
- `components/live/` — `MatchCentre` (scoreline, your players, then a
  collapsible detail), `LiveAnalyst` (the provisional reading of a match in
  play), `LiveCone`, `BonusDefconRail`.
- `components/advanced/` — `DecisionAudit`.
- `lib/` — `clock.ts` (the phase machine and countdown), `fdr.ts` (the one
  FDR scale), `chartTheme.ts` (the one chart language), `useFetch.ts`
  (polling: 10s Live, 60s elsewhere), `time.ts`.

Do not create `UniversalCard`, `UniversalPanel`, or
`UniversalDashboardSection`. Compositions here are authored per screen on
purpose; shared components exist for real football and system primitives,
not to avoid writing markup.


---

## 15. The restraint pass (2026-10-24)

Direct user feedback: cluttered, jargon, decoration, "aimless data". What was
removed or changed, as rules for what comes next:

- **Cards come from the frame.** `.screen-frame` turns every root-level child
  of a screen into a card; a wrapper that should not be one takes `bare`.
- **A screen has one headline and sections with sentence-case titles.** No
  giant ghost words behind a hero, no angled verdict block, no eyebrow above
  every title.
- **Collapse what a reader opens rarely.** A list of eighteen previews is
  eighteen one-line rows, open only where the user owns a player; a live card is
  scoreline and your players first, detail behind a toggle; engine-room
  readiness, source health and points revisions are disclosures.
- **A number with no decision attached is cut.** Category count boards, "904
  signals tracked", "170 tracked" and bonus-point revision lists with no effect
  on the squad went; the signal ledger that says whether a signal carries stayed.
- **No system words on a manager's screen:** solver, beam search, decision
  number, proven optimal, pipeline, raw snake_case source names. Where the
  mechanism matters it is said in football terms ("planned 42 min ago",
  "How fragile is the plan?").
- **Chip and status names are shown as people say them** (`chipName`), never
  as the API's identifiers.

## 16. Squad news and charts (2026-10-25)

- **Squad news** (`components/command/SquadNews.tsx`, `/api/squadnews`) sits under the decision sheet on Command and lists only
  players with something to say. Each line carries a source pill (Team sheet, FPL, FotMob, Return forecast, an outlet name);
  a headline is quoted as published and links out; nothing is generated and no statement is attributed to a manager that
  nobody made.
- **Distribution charts** (`EdgeDensity`): smooth curve, one-hue fade, the half left of the zero rule drawn in red when it is one
  series, and the share of trials on each side written on the rule.
