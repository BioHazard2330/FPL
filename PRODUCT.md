# Product

## Register

product

## Users

A single user: a Fantasy Premier League manager (aerospace engineering
background, comfortable with numerical/statistical reasoning) running their
own personal decision-support system for the 2026/27 FPL season. They open
this dashboard mid-week and on deadline day, under real time pressure, to
answer one question: what should I do right now, and why. They already know
FPL vocabulary (xP, EO, DGW, chips) and don't need it explained - but they do
need the system's own honesty markers (FACT vs MODEL vs FORECAST, confidence,
staleness) to stay legible at a glance, because the system's core promise is
that it never fabricates and never overstates certainty.

## Product Purpose

Take the user from preseason through GW38 answering: what should I do now,
and why. Recommend only, never auto-act. One authoritative decision per
question (transfer, captain, chip) - every panel either shows that same
decision or is clearly labeled as answering a different question. Success
looks like: the user can state the current recommendation and its single
biggest risk within 5 seconds of opening the page, and never once catches
the dashboard asserting something as fact that was actually a projection.

## Brand Personality

Football broadcast graphics (Sky Sports / Opta match-graphics package), not
SaaS-dashboard minimalism and not a betting slip. Three words: **decisive,
broadcast-grade, honest**. Bold use of real team colour/crest identity where
data supports it, stat-overlay confidence in how numbers are presented
(the way a broadcast graphic states a stat once, large, with zero hedging
in its TYPOGRAPHY even though the underlying number itself is honestly
uncertain) - the visual confidence is in the CRAFT, never smuggled into the
DATA. This is a tone shift from the dashboard's current near-monochrome
"restrained product" look toward something with more real team-colour
presence and graphic confidence, without loosening the project's own
non-negotiable precision/anti-fabrication rules (see CLAUDE.md) - those are
data-layer rules, not visual ones, and are never in tension with a bolder
visual system.

## Anti-references

- **Generic AI-SaaS dashboard.** Purple/blue gradients, glassmorphism,
  hero-metric-plus-sparkline cards repeated per section, identical
  rounded-card grids, side-stripe accent borders, gradient text. If it could
  be mistaken for a Vercel/Linear-template analytics starter, it has failed.
- **Sports betting sites.** Odds-board information density, flashing
  promos/badges, reflexive green-for-up/red-for-down on every metric
  regardless of what it's comparing against, urgency-manufacturing UI
  (countdowns, "X people viewing this offer" patterns).

## Design Principles

1. **Broadcast confidence in craft, never in data.** A number renders once,
   large, unhedged in typography - the honesty lives in explicit FACT/MODEL/
   FORECAST/confidence labels next to it, never in a softened visual
   treatment of the number itself.
2. **Team and player identity is real, not decorative.** Crests, kit colours
   and shirt graphics carry actual club identity everywhere a player/team is
   named - never a generic avatar or icon standing in for identity that
   real data already supports.
3. **One decision, one voice.** Visual hierarchy always makes the single
   authoritative recommendation the loudest object on the screen; a
   different question (a comparison, an alternative, a what-if) is always
   visually secondary, never competing for the same attention.
4. **Color is a role, not decoration.** Reuse this project's own established
   color-role table (positive/current/live/tactical/uncertainty/risk/
   captaincy - see `.claude/skills/fpl-visualization/SKILL.md`) - a color
   choice always answers "what role does this play," never "does this
   section need more color."
5. **Desktop is the product.** Design and verify at 1440px primary, 1080px
   secondary. Mobile stays usable, never a design target.

## Accessibility & Inclusion

Standard WCAG-reasonable contrast in both the existing dark and light
themes (already implemented via CSS custom properties). No additional
accommodation required - single known user, no stated color-vision or motor
constraints. Chart series colors should still remain distinguishable by
shape/position/label, not hue alone, as a general good practice, not a
stated hard requirement.
