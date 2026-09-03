---
name: fpl-visualization
description: Use when adding, reviewing, or auditing any chart in this project's dashboard - deciding whether a chart is warranted, which ApexCharts type fits the real analytical question, or whether an existing chart communicates anything. Applies to monitoring/dashboard/live_charts.py, match_centre.py, and any new chart added to command.py/myteam.py/football.py/scout.py/plan.py. Not for general layout/copy (see fpl-visualization's sibling fpl-football-intelligence for football copy, or the taste-repo skills for general frontend craft).
---

# FPL Visualization

This project already has real chart infrastructure: ApexCharts vendored at
`data/vendor/apexcharts.min.js`, a shared builder registry in
`monitoring/dashboard/assemble.py` (`window.fplInitCharts`), reusable
column/range/scatter/stepline builders in `monitoring/dashboard/live_charts.py`,
and match-specific momentum/shot-map rendering in `match_centre.py`. **Never
introduce a second charting library or a hand-rolled SVG chart** when an
ApexCharts type already covers the need (the project went through a full
ApexCharts consolidation pass on 2026-08-29 specifically to stop that
fragmentation - see CLAUDE.md's own known-blockers history). The one accepted
exception is the shot map (`match_centre.py::_shot_map_svg`) - genuinely
spatial pitch-coordinate data ApexCharts has no native chart type for.

## The rule this skill exists to enforce

**Never choose a chart because it looks impressive.** Before writing a single
line of chart code, state the real analytical question in one sentence. If you
cannot state it, do not build the chart. If an existing chart's question
cannot be stated by someone reading only its title and axes, the chart has
already failed and should be fixed or removed - not left because it exists.

## Chart type <-> question mapping (use this table, not taste)

| Chart type | Real analytical question | Project precedent |
|---|---|---|
| Time series (datetime axis) | How has this metric changed over time / across GWs? | `live_charts.py` rank trajectory, cumulative points |
| Stepline | How did a discrete, non-interpolating value change (FPL points only change at whole-GW boundaries)? | `live_charts.py` GW points |
| Range / range-area | How uncertain is this projection (floor/median/ceiling)? | `live_charts.py` projection range |
| Multi-line comparison | How do 2+ candidate trajectories compare against each other? | PLAN's per-path trajectory chart |
| Scatter | Which players are statistical outliers on two real axes (price vs xP, ownership vs xP)? | not yet built - real candidate, only build with real axis data, never fabricated jitter |
| Column / grouped column | Who is materially ahead, and by how much, on one or two real metrics? | `live_charts.py` captain contribution, actual-vs-expected |
| Diverging area | Which side had the pressure/advantage at each point in time, split above/below a zero baseline? | `match_centre.py` momentum |
| Heatmap / fixture matrix | Where is fixture/opponent difficulty concentrated across teams x GWs? | Fixture Tool's real FDR grid |
| Event timeline | What discrete football events changed a player's FPL outlook, and when? | FOOTBALL's signal feed (Part 3 of the 2026-09 visual rebuild) - currently list-rendered, not yet an ApexCharts timeline; a real, disclosed gap, not an oversight |
| Bar (proportional, non-axis) | Is A materially ahead of B, by a number the reader doesn't need to read an axis to judge? | COMMAND's decision-edge bars (`command.py::_edge_html`) - deliberately non-axis, see its own `floor = alt_total - ev*2` disclosure |

If a real request doesn't map cleanly onto this table, that is a sign to
reconsider whether a chart is the right representation at all - a single
number with real context (COMMAND's `+X.Xpts` treatment) often communicates
faster than a chart with one data point.

## Anti-patterns (reject on sight, in review or when writing new charts)

- Decorative charts with no stated question.
- Charts under ~200px tall on desktop carrying more than 2 data points -
  illegible, not just small.
- Two charts on the same screen answering the same question with different
  chart types (pick one).
- A chart whose only content is a single number - use the number itself
  (COMMAND's own `.cmd-edge-number` pattern), not a gauge/donut/single-bar
  chart around it.
- Multi-series line/area charts with more series than a reader can hold in
  working memory at once (~5-6 max) without a way to isolate one series.
- Green for every positive metric regardless of what it's comparing against -
  see the color-role table below.
- A chart with no visible units, no visible time window, or no visible series
  legend when more than one series is shown.
- Rebuilding a chart type ApexCharts already provides in hand-rolled SVG or
  Canvas "for a custom look" - extend the existing builder in `live_charts.py`
  instead (`buildColumn`'s `yMin`/`barColors`/`distributed` params were added
  for exactly this reason, 2026-09-02).

## Every chart states, visibly, on the page (not only in a code comment)

- **Title** - what it is.
- **The question** - a subtitle or caption stating what the reader learns
  (matches this project's existing `<span class="panel-subtitle">` convention
  used throughout `monitoring/dashboard/`).
- **Time window** - which GWs / which match / which lookback, explicit, never
  implied.
- **Units** - pts, xP, xG, %, £m - never a bare number.
- **Series meaning** - a legend when 2+ series; a single-series chart still
  needs an axis label stating what the numbers mean.
- **Source/freshness** - when the chart reads a cached/periodically-recomputed
  value (e.g. anything sourced from a `strategic_plan` decision rather than a
  live regen), say so - this project's own `decision_freshness.py` pattern,
  never let a chart imply a live number it doesn't have.
- **Uncertainty** - when the underlying number carries real, computed
  uncertainty (Monte Carlo floor/ceiling, `robustness.py`, `path_credibility.py`),
  show the range, not just the point estimate. A single-point projection
  chart next to a `FRAGILE` robustness label is a contradiction the user has
  to resolve themselves; the chart should carry the same honesty the decision
  layer already computed.

## Color is a role, not decoration

Reuse this project's real, established tokens (`assemble.py`'s `:root` CSS
variables) - do not invent a new ad-hoc palette per chart:

- `#00ff87` (`--accent`/`--ok-text`) - positive / selected / active / the
  chosen path or candidate.
- `#04f5ff` - structural "now"/decision-point emphasis (COMMAND's locked node,
  FOOTBALL's role/set-piece category accent).
- `#9d5cff` (added 2026-09-03 for TACTICAL_CHANGE) - tactical/comparison
  role, the project's first deliberate use of the `--fpl-purple` family for
  on-screen (not just brand-background) accent. Reuse for genuine "second
  candidate" / comparison-role series before inventing another purple.
- `#f0c419` - uncertainty / watch / review, never a confirmed-positive result.
- `#ff5c5c` / `#ff2882` - negative/risk (`#ff5c5c`) vs the captaincy-specific
  accent (`#ff2882`, reserved for the captain verdict word only, per
  `command.py`'s own established convention - do not reuse it for a generic
  "important" highlight).

A chart series' color should be chosen because of what role it plays (chosen
vs alternative, home vs away, attack vs defence), not because green "reads
positive" for an arbitrary metric with no inherent positive/negative sense.

## Desktop-first, explicitly

Design and verify every chart at 1440px first, 1080px second. A chart that
must shrink illegibly to survive 768px should collapse to a simpler
representation there (fewer series, a table, or a static summary), not be
designed AT the smallest size and stretched up. Do not spend implementation
effort on a mobile-specific chart layout for this project - matches the
project's own standing "no mobile shit" instruction.

## Verification

After adding or changing a chart, look at the real rendered result (see
`frontend-visual-qa`'s Level A/B evidence tiers) at 1440px with real
production data - never declare a chart correct from source/DOM inspection
alone. Confirm: the stated question is actually answerable from the rendered
chart, the axis/units are visible, and the color roles match the table above.
