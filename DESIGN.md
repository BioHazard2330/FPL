---
name: FPL Agent Dashboard
description: A personal FPL decision-support dashboard with broadcast-match-graphics confidence and zero data fabrication.
colors:
  bg: "#201f22"
  surface: "#0a0a0b"
  surface-2: "#141416"
  fg: "#ffffff"
  muted: "#a7a7b3"
  faint: "#6c6c78"
  border: "rgba(255,255,255,0.12)"
  gridline: "#232326"
  ok: "#22c55e"
  warn: "#fbbf24"
  bad: "#f0555a"
  accent: "#00ff87"
  structural-cyan: "#04f5ff"
  tactical-purple: "#9d5cff"
  captaincy-pink: "#ff2882"
  fpl-purple: "#37003c"
  fpl-pink: "#e90052"
  match-home: "#00ff87"
  match-away: "#04c8ff"
typography:
  display:
    fontFamily: "Oswald, Titillium Web, Impact, Arial Narrow Bold, sans-serif"
    fontSize: "2.7rem"
    fontWeight: 800
    lineHeight: 1.1
    letterSpacing: "normal"
  label:
    fontFamily: "Oswald, Titillium Web, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 700
    letterSpacing: "0.06em"
  body:
    fontFamily: "IBM Plex Sans, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: "5px"
  md: "8px"
  lg: "10px"
spacing:
  xs: "8px"
  sm: "14px"
  md: "20px"
  lg: "32px"
  xl: "48px"
components:
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.fg}"
    rounded: "{rounded.lg}"
    padding: "18px 20px"
  timeline-node-decision:
    backgroundColor: "transparent"
    textColor: "{colors.fg}"
    rounded: "{rounded.sm}"
    padding: "12px 16px"
  cmd-action-word:
    typography: "{typography.display}"
    textColor: "{colors.fg}"
---

# Design System: FPL Agent Dashboard

## 1. Overview

**Creative North Star: "The Match Graphics Package"**

This dashboard reads like the graphics overlay a broadcaster runs during a
match, not like an analytics SaaS product. A broadcast stat graphic states
one number, once, large, in a condensed athletic display face, with total
typographic confidence, even when the commentator is simultaneously hedging
in speech. This system borrows exactly that split: the CRAFT is confident
and immediate; the DATA stays honest through explicit, unhedged labels
(FRAGILE, MEDIUM confidence, RECOMPUTING) that sit right next to the bold
number rather than softening it. Team and player identity is real wherever
data supports it - official shirt graphics, club crests, team colour - never
a generic icon standing in for identity the data already carries.

This is a deliberate move away from the project's earlier, more generic
"dark analytics dashboard" phase (monochrome grey hierarchy, one thin
accent line, engineering-report density) toward a system with more real
colour presence and graphic confidence, without ever loosening the
project's own non-negotiable anti-fabrication rules - those are data-layer
rules and are never in tension with bolder visual craft.

**Explicitly rejected**: generic AI-SaaS dashboard cliches (gradient text,
glassmorphism, hero-metric-plus-sparkline cards, identical rounded-card
grids, side-stripe accent borders) and sports-betting-site energy (odds-
board density, flashing badges, reflexive green/red on every metric
regardless of what it's being compared against).

**Key Characteristics:**
- Condensed athletic display type (Oswald) for every number/verdict that
  matters; a plain humanist sans (Inter) for reading prose.
- Flat surfaces, tonal layering instead of shadows - the "broadcast lower
  third," not a floating card.
- Team colour and crest identity appear everywhere a club is named.
- A strict, already-established color-ROLE table (below) - never color
  picked because a section "needs more color."

## 2. Colors

Near-black tonal surfaces (a real broadcast-truck monitor in a dim room, not
a bright SaaS canvas) with a narrow, deliberate set of high-chroma accents
that each carry one specific meaning, never used interchangeably.

### Primary
- **Signal Green** (`#00ff87`): the one color that means "this is the
  chosen path / the positive outcome / the active state." Used sparingly -
  the decision word, the winning bar, the confirmed-positive tag.

### Full palette (product register, data-viz-heavy - four deliberate roles beyond primary)
- **Structural Cyan** (`#04f5ff`): "now" / a locked, structural decision
  point. Never used for a generic highlight.
- **Tactical Purple** (`#9d5cff`): tactical-change / second-candidate /
  comparison role.
- **Uncertainty Amber** (`#fbbf24` / warn text `#f0c419`): watch, review,
  fragile - never a confirmed-positive result.
- **Risk Red** (`#f0555a`) and **Captaincy Pink** (`#ff2882`, reserved
  strictly for the captain verdict word, never a generic "important"
  highlight).

### Secondary
- **FPL Purple** (`#37003c`) / **FPL Pink** (`#e90052`): the official Fantasy
  Premier League brand pair - used sparingly for real FPL-brand moments
  (a left accent on FPL-sourced content blocks), never as a general UI
  accent competing with the primary/full-palette roles above.
- **Match Home/Away** (`#00ff87` / `#04c8ff`): reserved strictly for Match
  Centre's own home-vs-away team-color coding (momentum chart, score line)
  - a distinct, narrower role from the primary/tactical/structural accents
  above even though `#04c8ff` sits close in hue to Structural Cyan; never
  reuse one for the other.

### Neutral
- **Near-black Surface** (`#0a0a0b`): card/panel background.
- **Charcoal Surface-2** (`#141416`): a second, slightly lighter tonal step
  for nested/secondary surfaces - never a shadow, a lighter tone instead.
- **Page Ground** (`#201f22`): the page background, one step lighter than
  surfaces so cards read as real objects sitting on the page.
- **Muted Grey** (`#a7a7b3`) / **Faint Grey** (`#6c6c78`): secondary and
  tertiary text.
- **Hairline Border** (`rgba(255,255,255,0.12)`): the only border weight
  used at rest.

A parallel light theme exists (`prefers-color-scheme: light` /
`data-theme="light"`), remapping every token to a light-ground equivalent -
same roles, inverted lightness, never a separate palette to maintain.

### Named Rules
**The One Role Rule.** Every accent color answers "what role does this
play" (current / structural / tactical / uncertainty / risk / captaincy) -
never "does this section need more color." A color used for two different
roles on the same screen is a bug, not a style choice.

**The Broadcast-Truck Rule.** Neutrals stay near-black and tonal, never a
bright SaaS-white canvas, even in the light theme (which lightens without
ever hitting pure `#fff`).

## 3. Typography

**Display Font:** Oswald (with Titillium Web, Impact, Arial Narrow Bold, sans-serif fallbacks)
**Body Font:** IBM Plex Sans (with system-ui, -apple-system, Segoe UI, sans-serif fallbacks) - self-hosted, `data/vendor/fonts/ibm-plex-sans.woff2`

**Character:** A condensed, all-caps-capable athletic display face (the
same family broadcast lower-thirds and stadium scoreboards use) paired with
a plain, highly-legible humanist body face. The pairing is the whole
"broadcast graphics, not SaaS" argument stated in two font choices.

### Hierarchy
- **Display** (800, 2.7rem `.cmd-action-word`/`.hero-verdict-word`, 1.1
  line-height): the one authoritative decision word per screen (PLAY
  WILDCARD, ROLL). Appears once. Never a headline treatment for something
  that isn't the primary decision.
- **Label** (700, 0.75rem, 0.06em tracking, uppercase, Oswald): section
  labels, tags, GW badges, chip badges - short, athletic, always uppercase.
- **Body** (400, 0.95rem, Inter, 1.5 line-height): prose, evidence
  sentences, table cells. Cap line length near 70ch where prose runs long
  (football-evidence sentences).
- **Data label** (`--fs-2xs` through `--fs-xl`, an existing 6-step scale
  currently only fully applied in Match Centre): numeric/tabular values -
  `font-variant-numeric: tabular-nums` throughout so numbers align in
  columns.

### Named Rules
**The One Verdict Rule.** Display-scale type is reserved for the single
authoritative recommendation on a screen. A comparison or alternative
value never renders at display scale, no matter how important it feels in
the moment - scale is the hierarchy signal, not color or weight alone.

## 4. Elevation

Flat by default - tonal layering (surface -> surface-2, one step lighter)
does the depth work a shadow would, matching a broadcast graphic's flat
plate rather than a floating SaaS card. No box-shadow anywhere at rest.
The one exception: the player-inspector drawer, a real slide-in panel,
carries a directional shadow (`-20px 0 50px -20px rgba(0,0,0,0.6)`) because
it's genuinely elevated above page content, not decoratively "lifted."

### Named Rules
**The Flat-By-Default Rule.** A surface is flat at rest. The only thing
that ever separates two surfaces is a hairline border or one tonal step,
never a shadow used for decoration.

## 5. Components

### Buttons / Tabs
- **Shape:** small radius (5px, `--rounded-sm`), never pill-shaped except
  status dots and chip badges (intentionally circular/pill for those two).
- **Primary (nav-active / path-selected):** transparent background, color
  shift to `--fg`/`--accent-2`, never a filled background at rest - the
  underline/border-color carries the "selected" state.
- **Timeline node (signature component):** a multi-row card-button (GW
  label / action word / chip badge stacked) - deliberately NOT a
  single-line label; this is the system's own athletic "match-clock event"
  metaphor, not a generic button.

### Cards / Panels
- **Corner style:** 10px radius (`--rounded-lg`).
- **Background:** `--surface`, one hairline border (`--border`), never a
  shadow.
- **The Real-Structure Rule:** a card is used only when it represents one
  real, distinct object (a player, a path, a team) - never as a generic
  content wrapper. Text that doesn't represent a discrete real object
  should not be boxed.

### Shirts / Crests (signature component)
Real official FPL shirt graphics (`fantasy.premierleague.com` CDN) and
cached club crests appear everywhere a player or team is named - this is
the system's actual identity language, doing the work a generic avatar or
icon would do elsewhere. Never a placeholder silhouette when the data to
resolve a real shirt/crest exists.

### Navigation
Sticky top bar, horizontally scrollable with an edge fade below ~900px,
uppercase Oswald labels, muted at rest, `--fg` on hover/active - no pill
background, no underline, color shift alone carries state.

### Charts
ApexCharts exclusively (one chart type per real analytical question - see
`.claude/skills/fpl-visualization/SKILL.md`, which this file defers to for
the full chart-type <-> question mapping and the canonical color-role
table this section's palette is drawn from).

## 6. Do's and Don'ts

### Do:
- **Do** render the single authoritative decision at display scale (2.7rem,
  Oswald 800), once per screen.
- **Do** use real shirt/crest graphics for every named player/team.
- **Do** keep every accent color tied to its one role (current/structural/
  tactical/uncertainty/risk/captaincy) from the Colors section above.
- **Do** state a number once, plainly, then carry its honesty label
  (confidence/staleness/FRAGILE) as a separate, explicit tag beside it.

### Don't:
- **Don't** use gradient text, glassmorphism, or a hero-metric-plus-
  sparkline card template - named anti-references from PRODUCT.md.
- **Don't** build betting-site energy: no flashing badges, no reflexive
  green-for-up/red-for-down regardless of what's being compared, no
  manufactured urgency.
- **Don't** use `border-left`/`border-right` greater than 1px as a colored
  accent stripe on any card or row.
- **Don't** add a box-shadow to a surface at rest - tonal layering only.
- **Don't** invent a new accent color for a component "because it needs
  more color" - reuse an existing role or leave it neutral.
- **Don't** soften a number's typography to hedge uncertainty - the hedge
  belongs in an explicit label, never in the number's own visual weight.
