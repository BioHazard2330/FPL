---
name: FPL Agent
description: A personal FPL decision terminal styled as a live match-graphics package, not a SaaS dashboard.
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
  tag-block-hover:
    backgroundColor: "{colors.divider}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.none}"
    padding: "6px 12px"
  live-pill:
    backgroundColor: "{colors.alert-red}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.pill}"
    padding: "3px 10px"
---

# Design System: FPL Agent

## 1. Overview

**Creative North Star: "The Scoreboard Bug"**

Every screen reads like the graphics package running under a live match
broadcast: a scoreboard bug, a half-time stat graphic, a deadline-day
build-up ticker. Flat, confident color blocks stand in for cards. Condensed,
oversized numerals stand in for hero metrics. Angled cuts and thick rule
dividers stand in for borders and shadows. Nothing glows, nothing is glass,
nothing fades in gradient - broadcast graphics are opaque, fast to read at a
glance, and never apologize for taking up space.

This explicitly rejects the generic AI-dashboard look this project already
built once and threw out: dark background plus cyan/purple neon glow,
glassmorphism panels, monospace numerals worn as a costume instead of used
as a typographic decision, gradient text, a soft-shadowed rounded card
repeated for every fact regardless of importance. None of that survives
here. Where the old pass reached for a glow ring, this system reaches for a
flat color block and a diagonal cut instead.

The single user is fluent in dense data (an engineering background) and
wants the verdict fast - so density is not the enemy of boldness here.
Broadcast graphics are *both* dramatic and information-dense (a scoreboard
bug carries score, clock, and possession in one confident glance) - this
system holds both at once rather than trading one for the other.

**Key Characteristics:**
- Flat color blocks, never gradients or glow, as the primary way information is grouped
- Oversized condensed numerals for hero verdicts; disciplined, denser type for tables and lists
- Angled (`clip-path`) cuts and thick rule dividers replace soft shadows and glass borders
- Near-black, cool-tinted canvas - broadcast-truck darkness, not "dashboards are dark by default"
- One flat accent per semantic category (verdict, captain/premium, informational, danger) - never decorative

## 2. Colors

Flat and saturated where broadcast graphics are saturated - color blocks, not accents on a neutral field.

### Primary
- **Pitch Green** (#1FCE6B): the verdict color - the primary recommended action, positive deltas, "this is the answer" moments. Used as a full flat block behind the hero verdict, not as a glow or a thin accent line.

### Secondary
- **Broadcast Gold** (#F0A93E): captaincy, premium/hero picks, anything that should read as "the standout." A deliberately warm, non-neon amber - trophy and premium-broadcast association, nowhere near the AI-slop cyan/purple family.

### Tertiary
- **Broadcast Blue** (#2D6CDF): informational category tag for chip/transfer-type actions and neutral data callouts - a confident, saturated blue, not a desaturated "info gray."

### Neutral
- **Void** (#0A0E14): the base canvas - near-black, cool-tinted, never pure `#000`.
- **Panel** (#12171F): the first surface layer above the canvas (section backgrounds).
- **Raised** (#1A2029): the second surface layer (tag blocks, table row hover, nested groupings).
- **Divider** (#232B36): rule lines between sections - used instead of card borders/shadows for separation.
- **Text Primary** (#F5F3EE): warm off-white, never pure `#fff`.
- **Text Muted** (#9099A8): secondary text, supporting stats.
- **Text Faint** (#5B6472): tertiary text, timestamps, disabled-adjacent labels.
- **Alert Red** (#E3452F): danger/sell/fragile state - a real broadcast red, not a neon warning glow.

## 3. Typography

Two typographic registers, deliberately: a **display** register for the handful of genuine hero moments (the verdict headline, a scoreboard number), and a **data** register for everything else (tables, lists, labels, body copy) that stays dense and legible rather than dramatic. This is the one place this system departs from "product UI wants a tight, single-family scale" on purpose - broadcast graphics packages do exactly this (a huge scoreboard numeral next to a small dense stat line), and the brand-personality exception PRODUCT.md documents is granted specifically for this.

- **Display** - Oswald 700, condensed and tall, `clamp(3.5rem, 8vw, 7rem)`. The verdict word/phrase only. Nothing else earns this size.
- **Headline** - Oswald 600, 1.75rem. Section identifiers that need real presence (a screen's own title treated as a scoreboard-bug label), used sparingly.
- **Label** - IBM Plex Sans 700, 0.6875rem, `0.12em` tracking, uppercase. Category tags, stat labels - the small bold caption under every number.
- **Body** - IBM Plex Sans 400, 0.9375rem. Prose, explanations, reasoning text. Capped at 65-75ch.
- **Data** - IBM Plex Sans 600 with tabular numeral features (`font-feature-settings: "tnum"`), 1rem. Every real number (prices, xP, deltas) aligns on this - a genuine typographic decision (tabular figures on the SAME family), not a monospace family worn as a "tech" costume.

Monospace is not used anywhere in this system. IBM Plex Mono (used in the previous pass) is dropped entirely - it was decoration, not a real typographic choice.

## 4. Elevation

Flat. No shadows, no blur, no glass. Layering is communicated by flat surface color (void -> panel -> raised) and by angled `clip-path` cuts on hero blocks, the same way a broadcast graphics package layers a scoreboard bug over live video without ever using a drop shadow. A thick (2-4px) solid rule divider does the separation work a card border or shadow would otherwise do.

## 5. Components

- **Verdict block**: the hero recommendation. A full-bleed flat Pitch Green (or category-appropriate color) block, one angled edge (`clip-path: polygon(...)`), the Display headline in Void-colored text directly on the block - not white text on a dark card with a colored accent, the block itself IS the color.
- **Stat strip**: a horizontal row of flat-background stat cells (Raised surface), each with a Label caption above a Data numeral - modeled on a live match stat ticker, not a grid of bordered KPI cards.
- **Tag block**: flat Raised-surface rectangle, sharp corners, Label typography - category/status tags. Never a soft rounded pill except the one deliberate exception below.
- **Live pill**: the ONE rounded, pill-shaped element in the system, reserved exclusively for a genuinely live/real-time state (a live match, a live rank tick) - Alert Red or Pitch Green fill depending on state, so the pill shape itself becomes a real signal ("this one thing is live") rather than a default shape.
- **Data table row**: dense, Data typography for numerals, Raised-surface hover, a Divider rule between rows - no card wrapper around individual rows.
- **Comparison bar**: a flat, rectangular (not pill) fill bar for chosen-vs-alternative comparisons - a thick marker line for the alternative, no gradient, no glow.

## Phase 8.3 addendum (exhaustive 21st.dev research, validated + extended)

The exhaustive catalogue crawl (`docs/21ST_EXHAUSTIVE_CATALOGUE.md`, 749 real
components across all 77 live categories) confirmed this system's core direction
rather than changing it - the closest real 21st pattern to broadcast/scoreboard
graphics (Bento Dashboard's neo-brutalist flat-bar-chart + ghost-watermark language)
independently converges on the same flat-block, no-glow, condensed-display-type
grammar this system already committed to. Two real additions from that research:

- **Flat tag chips** (Records Table pattern) - a table row's category/risk markers
  are small, fully-filled flat color rectangles (never a translucent badge), several
  per row where genuinely needed - the SCOUT/ADVANCED table language.
- **Blur-transition numerals** (Number Flow pattern) - a second `CountUp` mode
  reserved for a value that changes AGAIN while already on screen (live rank, live
  points) - a per-digit blur in/out, distinct from the existing ease-out count used
  for a value's first arrival.

## 6. Do's and Don'ts

**Do:**
- Use flat color blocks and angled cuts to group and separate information.
- Reserve the Display register for genuine hero moments - one per screen, maybe two.
- Keep tables and dense data in the Data/Label registers, disciplined and tight.
- Let one category own a section's color (a chip-type verdict is Blue throughout, not Blue-plus-random-accent).
- Use real crest/shirt imagery where the product already has it (My Team's pitch) as the actual visual interest, not a decorative background.

**Don't:**
- Use any glow, gradient fill, or `background-clip: text` gradient numeral - the single most-repeated failure of the previous pass.
- Reach for glassmorphism/blur cards.
- Use monospace as a "tech dashboard" costume - tabular numerals on the real body family instead.
- Put a rounded-corner ring/border on every card - most panels here are sharp-cornered flat blocks, not bordered cards.
- Repeat the same bordered-card treatment for every fact regardless of importance - a scoreboard bug never gives a substitution and the final score equal visual weight.
