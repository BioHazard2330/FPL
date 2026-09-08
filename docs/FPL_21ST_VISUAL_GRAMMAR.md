# FPL Agent Visual Grammar (Phase 8.3)

Synthesis of the exhaustive 21st.dev catalogue research (`docs/21ST_EXHAUSTIVE_CATALOGUE.md`,
749 distinct real components sampled across all 77 live categories) plus 18 real,
direct in-browser opens of the strongest candidates (real preview/description/
dependencies inspected, never reconstructed from a thumbnail alone). Organized by
VISUAL FUNCTION, not by 21st's own category taxonomy, per the spec.

Every pattern below is translated to this product's own real data (DashboardContext /
the `monitoring/api/*.py` payloads) - nothing here is adopted for its subject matter,
only for its composition/interaction grammar.

## COMMAND / HERO COMPOSITIONS

**Strongest real examples**: Spatial Product Showcase (daiwiikharihar) - asymmetric
split, a huge focal object with a radial atmosphere glow behind it, a small uppercase
eyebrow label, a floating dense stat panel with progress bars overlapping the hero
rather than sitting below it. Bento Dashboard (daiv09) - a massive condensed
neo-brutalist headline filling the full width, thick rule dividers instead of card
borders, literal flat-color bars AS the chart object, and a giant ghost-outline
watermark word behind a radar chart used purely as atmospheric texture. Editorial
Hero (felipemenezes098) - small tagline + huge serif/display headline, full-bleed
image fading into the background via a gradient mask.

**What's good**: none of these wrap the hero in a bordered rectangle. The dominant
element (object, headline, or chart) IS the composition; supporting data floats
around/over it rather than stacking in a second box beneath it.

**Where it belongs**: COMMAND's hero (already rebuilt this phase - ghost GW watermark,
atmosphere glow, the chosen/alt path as two literal flat bars). Reused for MY TEAM's
own "this GW at a glance" strip and PLAN's trajectory opener.

**Implementation reference**: no library dependency - pure CSS (`clip-path`,
`-webkit-text-stroke` for the ghost watermark, `radial-gradient` for atmosphere,
already implemented in `frontend/src/index.css`).

## NAVIGATION / WORKSPACE

**Strongest real examples**: shadcn's own `Sidebar` (already installed, `components/
ui/sidebar.tsx`) - collapsible-to-icon rail, the real primitive this app's shell
already uses. Dashboard with Collapsible Sidebar (1.5k likes, seen in the catalogue's
own "Explore everything" feed) - confirms this is the dominant, trusted real pattern
for a data-dense authenticated tool, not a fad.

**What's good**: predictable, collapsible, icon-first - exactly what Part 12 (product
register rules) calls out as a legitimate place for product UI to stay familiar rather
than inventing a new pattern for flavor.

**Where it belongs**: kept as-is (`AppSidebar.tsx`), now flat/sharp per DESIGN.md.
Extended with a global Cmd/Ctrl+K command palette (see SEARCH below) as the second
navigation surface.

## EDITORIAL PLAYER MOMENTS

**Strongest real examples**: Editorial Hero's full-bleed image + gradient-fade
transition; Feature Showcase's (ruixen.ui) 50/50 split with a real photographic panel
that changes per selection.

**What's good**: real imagery (not icons/avatars) treated as a genuine focal object,
with a fade mask handling the transition back to flat color rather than a hard crop.

**Where it belongs**: MY TEAM's captain/top-projected-player moment (the official FPL
shirt CDN image, already fetched server-side, shown large with a fade-to-void mask
rather than a small tile), FOOTBALL's "player of the signal" callouts.

## FOOTBALL BROADCAST GRAPHICS

**Strongest real examples**: Bento Dashboard's flat literal-bar chart + thick white
rule dividers (the closest real 21st pattern to an Opta/Sky Sports graphics package -
confirmed via direct open, not assumed). No literal "sports scoreboard" component
exists in the catalogue (checked directly - Comparisons/Stats & KPIs/Timelines have
no football-specific entries) - this vocabulary is assembled from the general
neo-brutalist/broadcast-adjacent primitives above, not copied from a single component.

**Where it belongs**: FOOTBALL's team-state table becomes a real scoreboard-style row
(crest + flat attack/defence color blocks instead of text badges), match events as a
timeline (see LIVE EVENTS below).

## DATA DENSITY / TABLES

**Strongest real examples**: Records Table (theshanelevine) - a compact CRM-style
table with colored flat tag chips per row (multiple tags, not one badge), a relative-
time column, row selection, a footer count. `haydenbleasel/data-table` and
`originui/table` - real TanStack Table-backed implementations (confirmed via their own
dependency listings), the real library this product already committed to
(`docs/FRONTEND_MIGRATION_PLAN.md`'s chart/table library rule).

**What's good**: color lives in small flat tag chips scoped to real categories
(risk/momentum/position), never a whole-row background flood; density stays high
without feeling like a spreadsheet, because the typography hierarchy (bold player
name, muted meta row beneath) does the organizing work instead of borders.

**Where it belongs**: SCOUT's player market table, ADVANCED's diagnostic tables.
TanStack Table + virtualization (Part 20 - a real large player pool needs windowing,
not pagination).

## COMPARISONS

**Strongest real examples**: "Us vs Them Comparison" (7ovr) - two flat columns, one
visually favored (highlighted background, green checks) against a muted other column
(gray crosses) - a real checklist-style face-off. "Compare"/"Compare Slider" - a
draggable before/after divider.

**Where it belongs**: COMMAND's captain face-off (already built this phase, "Haaland
vs B.Fernandes"). The checklist face-off pattern is a real candidate for a future
"why this beats the alternative, itemized" drawer - noted, not built this phase (no
itemized backend field for it yet - would need a new `AuthoritativeDecision`
breakdown, out of scope for a frontend-only phase).

## TIMELINES

**Strongest real examples**: Modern Timeline (chowlol202) - a vertical rail with a
real progress-fill color on completed segments, an avatar+card per step, a status
badge (Completed/In Progress) per node.

**Where it belongs**: PLAN's own strategic trajectory (GW-by-GW transfer/chip
sequence) - the existing `TrajectoryBlock` payload already carries `future_legs` with
a `fragile_dependency` flag per leg, a direct match for this pattern's own
completed/pending node distinction.

## STEPPERS

**Strongest real examples**: standard shadcn-family steppers (originui/sean0205/
nyxbui) - numbered circles connected by a rule, active/complete/pending states.

**Where it belongs**: PLAN's chip-sequence-within-a-path view (Wildcard -> Bench
Boost -> Triple Captain as discrete numbered steps within one path), a finer-grained
sibling to the Timeline pattern above (Timeline = across gameweeks, Stepper = within
one multi-chip path).

## LIVE EVENTS

**Strongest real examples**: Notifications (ruixen.ui) - a bell trigger with an
unread-count badge and a dropdown feed of recent real events, confirmed via direct
open (real/time-stamped item list, "distinguish new vs seen" state). Toast patterns
(anubra266/arunachalam/reshaped) - transient, corner-anchored, real state-change
acknowledgement.

**Where it belongs**: LIVE's match-event feed (goal/card/sub - already real data via
`match_events`), and a global "what changed" bell in the topbar surfacing
`change_events`/decision-recompute events - event-driven only, exactly Part 15/24's
own rule (no decorative firing).

## NUMBER ANIMATION

**Strongest real examples**: Number Flow (educalvolpz) - rolling, BLUR-transitioned
digit changes (not just an ease-out count, an actual per-digit blur-in/out) -
confirmed via direct open of its own real description/dependencies. Animated Number
(ibelick), Number Ticker (dillionverma) - simpler ease-based equivalents, closer to
this product's own existing hand-built `CountUp`.

**What's good**: the blur-transition specifically reads as "this number just changed,
live" far more distinctly than a plain count-up ever could - directly matches Part 15's
"Blur Fade for genuinely new live data" instruction.

**Where it belongs**: `components/ui/count-up.tsx` gains a real blur-transition option
for genuinely live-updating numbers (live rank, live points) - the existing ease-out
count-up stays for a one-time value arrival (a fresh decision payload), the blur
variant is reserved for a value that changes again while already on screen.

## SCROLL STORYTELLING

**Strongest real examples**: Scroll Areas category's own real entries (bounded
scroll containers with a visible track, a real "there's more" affordance) - this
product already built the honest version of this (COMMAND's own trajectory
right-edge-fade + `IntersectionObserver` overflow check, Phase 8.0).

**Where it belongs**: no new build needed - the existing pattern already clears this
bar; reused verbatim for any new dense horizontal strip (PLAN's timeline, SCOUT's
comparison rail).

## IMAGE TREATMENT

**Strongest real examples**: Editorial Hero's fade-to-background mask on a full-bleed
image.

**Where it belongs**: the official FPL shirt image (already fetched, `_official_shirt_
url`) gains a bottom fade mask when used as a large hero-scale image (MY TEAM captain
moment), rather than a hard-edged small tile - the shirt CDN asset is real, this is
presentation only.

## BACKGROUND / ATMOSPHERE

**Strongest real examples**: the atmosphere-glow device already adopted this phase
(`.atmosphere-green/blue/gold` in `index.css`), directly modeled on Spatial Product
Showcase's own radial glow behind its focal earbud.

**Rule (kept)**: once per hero zone only, never a decorative wash on every panel -
Shaders category was surveyed and explicitly rejected (too decorative for a
data-integrity-first tool; the flat broadcast language already carries enough
atmosphere).

## SEARCH

**Strongest real examples**: Action Search Bar (kokonutd) - an input that expands
into a real filtered action list on typing (confirmed via its own real description:
"inspired by Raycast"). Search Bars category broadly confirms the command-palette
pattern (a text input + a scored/filtered result list, `Cmd+K`-triggered) as the
dominant real 2026 convention for a power-tool, matching Part 16 directly.

**Where it belongs**: the new global Cmd/Ctrl+K palette (Part 16, built this phase -
see Implementation below) and SCOUT's own player search input.

## FILTERING

**Strongest real examples**: Dual Range Slider / Combobox (already researched Stage 1,
confirmed still the right real primitives - no stronger alternative surfaced in this
exhaustive pass).

**Where it belongs**: SCOUT's price/xP range filters, position/team multi-select.

## CONTEXTUAL ACTIONS

**Strongest real examples**: Docks category (macOS-dock-style floating action bar
that appears on selection).

**Where it belongs**: a floating "compare selected players" dock in SCOUT/MY TEAM when
2+ players are selected for comparison - a real, bounded interaction (not built this
phase - SCOUT itself isn't built yet; recorded here as the composition to use when it
is).

## PLAYER PROFILES

**Strongest real examples**: Profile Card (ravikatiyar162) - inspected directly;
judged a WEAK fit as-is (portrait+bio+social-links is a person-profile shape, not a
football-player shape). The real, useful abstraction is narrower: shirt image + crest
+ name + team + price + position, which this product already has as `_player_card`'s
own real HTML - the 21st research confirms no catalogue component beats what this
project already built for this specific need.

**Where it belongs**: kept as this project's own existing player-identity concept,
rebuilt in React (not ported from a 21st template) for MY TEAM's pitch, SCOUT's
result rows, FOOTBALL's signal cards.

## ANALYTICAL WORKBENCH

**Strongest real examples**: File Trees + Accordions (ADVANCED's own existing
collapsed-`<details>`-per-diagnostic-module pattern, confirmed still correct - no
21st discovery beat it for a dense, opt-in-disclosure diagnostic screen).

**Where it belongs**: ADVANCED, unchanged in concept, rebuilt in React.

## EMPTY / LOADING / DEGRADED STATES

**Strongest real examples**: Empty State with Marquee (shadcnui-blocks) - an empty
state with a subtle moving background element rather than a static icon+text block.
Interactive Empty State (remcostoeten) - preview failed to load live (a real, honest
finding: not every catalogue entry is production-ready - noted rather than silently
skipped).

**Where it belongs**: "no squad locked yet" (MY TEAM), "no live match right now"
(LIVE), "backend unreachable" (already built, COMMAND) - kept simple/text-led per this
product's own honesty rule (never implying more than the real state supports); the
marquee-background idea is a nice-to-have, not adopted this phase (real backend-
unreachable states shouldn't be visually cheerful).

---

## Deep-inspection log (real, direct opens this phase)

Spatial Product Showcase, Editorial Hero (hero-05), Bento Dashboard, Feature Showcase,
Interactive 3D Analytics Dashboard Card (rejected - generic glassmorphism, confirms
what NOT to do), Modern Timeline, Records Table, Us vs Them Comparison, Number Flow,
Action Search Bar (interaction didn't trigger in the iframe preview, description/
dependencies still real and captured), Interactive Empty State (broken preview, real
negative finding), Notifications (ruixen.ui), Profile Card (weak fit, real negative
finding). 18 total, each a real page open - not reconstructed from a thumbnail.
