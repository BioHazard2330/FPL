# Session 24 — 2026-08-29: continuation, major perf bug fix + more fpl.page parity

Direct user instruction: "Continue with everything remaining" (from session 23's disclosed-gap
list). Worked through the list in priority order, auditing each item against the real codebase
before building - several turned out to already be substantially covered (Intelligence panel's
WHAT CHANGED/WHY IT MATTERS/FPL IMPACT/CONFIDENCE structure, source-health primary/secondary
split), verified not rebuilt.

## Major finding: real live-snapshot performance bug, found + fixed

While investigating the "Live Charts"/"performance profiling" asks, profiled
`monitoring/live_snapshot.py::build_live_snapshot` directly against production: **6.6 seconds**,
almost entirely inside `get_locked_squad()` → `_xi_from_real_picks()` → `build_player_pool(conn,
n_gw=1)`. That call runs a REAL full ~600-player Dixon-Coles/Monte-Carlo xP scan just to look up
the 15 already-known picked player ids. `get_locked_squad()` is the one real caller on the hot
path of the live-match poll's own ~20-25s tick - the exact cadence `live_snapshot.py`'s own
docstring promises stays cheap ("never runs Dixon-Coles, Monte Carlo... those stay on their own
expensive, materiality-gated cadence"). This silently violated that contract every single tick,
undoing the whole point of the 2026-08-28 perf fix that introduced this "cheap channel" in the
first place.

Fixed: swapped in `build_player_pool_for_ids` (already existed, already used by
`resolve_projected_xi` for the same "known small id set" case) - same real per-player xP,
correctly scoped. Measured 237ms post-fix (~26x faster); `build_live_snapshot()` end-to-end:
6.6s → 223ms. 24 locked-squad/live-snapshot tests green, no behavior change (same real values,
just not recomputed for ~585 players that were never going to be used).

## New features (fpl.page-parity list)

1. **Fixture Tool "Rotation" sort + Reset control**: no real per-player rotation-risk model
   exists (checked - `minutes_distribution.py` gives per-player probability, not team-level
   congestion), so rather than fabricate one, reused the already-built, already-tested
   `detect_blank_double_gws` (the same real blank/double-GW detector the chip-timing DP already
   uses) as an honest, FPL-specific "rotation planning" signal. DGW/BGW badges on team rows, a
   real sort mode, and a Reset button restoring every control to its default.
2. **Opportunity Board "MY SQUAD IMPACT"**: real "Would replace X" line when a card's player is
   one of `analyze_transfer_decision`'s own already-computed `ta.candidates` - never a second,
   invented replacement guess, absent (not "?") when the player genuinely isn't a real candidate.
3. **Intragame live-rank chart**: real gap closed - "intragame charts must still work during a
   live GW, do not wait for a completed GW" was previously blocked on "no per-tick storage
   exists." Turned out unnecessary: every real `fpl live-rank`/`_maybe_refresh_livefpl_rank` call
   already appends a new row to the append-only decisions journal (`log_decision(..., "live_rank",
   ...)`, never overwritten) - a real time series was already accumulating, just never queried
   for a chart. `render_intragame_rank_chart` reads it directly, degenerate-precision samples
   excluded (same trust rule the rank tile itself applies), `''` with fewer than 2 real samples.
4. **Player Inspector FOOTBALL section**: the squad-pitch player drawer gained a real per-player
   football signal line, reusing `models.player_intelligence.player_intelligence`'s already-
   computed current outlook/confidence (memoized once per player per regen) - absent, never
   fabricated, when no real qualitative state exists for that player yet.

## Dead-CSS audit round 2 (scripted, cross-checked against dynamic f-string construction)

Found and removed a genuinely large dead cluster from the pre-Plan-workspace "Strategy Explorer"
panel (superseded 2026-08-27, never cleaned up): `.strategic-current`, `.strategic-primary`,
`.strategic-twocol`, `.strategic-col`, `.strategic-horizon-table`, `.strategic-subrow` (bare),
`.strategic-alt-list`, `.strategy-timeline-track`, `.strategic-path-card`, `.strategic-path-
header`, `.strategic-path-step.timeline-node` (+ its dead child selectors referencing
`.strategic-path-gw`/`.strategic-path-action`, neither ever emitted by the current Plan
workspace, which uses `.timeline-node-gw`/`.timeline-node-action` instead), plus `.hero-watch`,
`.refresh-indicator`, `.risk-monitor` (container - `.risk-row`/`.risk-severity` children are
real and kept), `.fdr-stat`, `.squad-state-player` (bare, `-in`/base already removed prior
session), `.ok-line`/`.warn-line`. ~35 confirmed-dead rules total this pass, each verified by
exhaustive literal-string AND f-string-interpolation grep across the whole `monitoring/
dashboard/` package (not just a naive count, after a real false-positive from that shortcut last
session).

**Found + fixed a real, second bug via this audit**: `.opp-card-price .opp-card-kind { color:
var(--ok-text); }` never matched anything - the Value category's real emitted class is
`.opp-card-value` (`kind.lower().replace(' ','-')` on the literal string `"Value"`), not
`.opp-card-price` (a stale name from before that category was renamed). The Opportunity Board's
Value cards have been silently missing their intended kind-label color the whole time. Fixed by
renaming the selector to match the real emitted class.

Also removed `.timeline-node.is-active { border-color: var(--accent-2); ... }` (legacy.py) -
a real, currently-losing duplicate of `assemble.py`'s own `.timeline-node.is-active` rule (same
selector, different values; `assemble.py`'s `_CSS_WORKSPACE` loads after `legacy.py`'s `_CSS` in
the page, so the legacy.py copy never actually wins the cascade - real, harmless-in-practice,
but genuine dead weight).

## Verified already-solved, not rebuilt

- Intelligence panel's WHAT CHANGED / TEAM / WHY IT MATTERS / FPL IMPACT / CONFIDENCE structure
  (`intelligence.py::render_what_changed_html`/`_team_signal_card`) - direct spec ask, already
  built 2026-08-27, confirmed by reading the module's own docstring and code, not rebuilt.
- Source-health primary/secondary split (`_health_summary_html` one-line rollup + `<details>`
  drill-down with per-source last-success) - already built 2026-08-21.

## Not attempted this pass, honestly disclosed

- Full News → Decision structured pipeline (SOURCE → CLAIM → ENTITY → STATE CHANGE → MODEL
  IMPACT → DECISION IMPACT) beyond the existing captain/OUT/IN tags - real, scoped, its own
  session.
- Squad-contribution / captain-contribution / actual-vs-expected intragame charts - real per-tick
  storage still doesn't exist for these (unlike live-rank, which turned out to already be
  logged); would need a genuinely new write path, not just a new read.
- Full Player Inspector BUY/HOLD/SELL/WATCH/REVIEW vocabulary and Solio/MARKET per-player rows -
  the FOOTBALL section closes one real gap; MARKET would need a per-player Solio comparison
  wired into the same drawer (real, larger, deliberately not rushed into the hot per-card path).
- A dedicated visual-redesign audit against fresh fpl.page screenshots.
- A full remaining sweep of `.strategic-*`/pre-redesign CSS beyond what this pass's audit
  actually traced end-to-end - the confirmed-dead rules above were each individually verified;
  a broader systematic pass across the whole `_CSS` block was not attempted.

## Verification

- New/updated tests: `test_dashboard_workspaces.py` (+1 rotation test), `test_dashboard_
  opportunity_board.py` (+2 squad-impact tests), `test_live_charts.py` (+4 intragame-chart
  tests), `test_dashboard.py` (+1 football-signal test, +1 chip-explanation test from the
  session-23 continuation).
- Full suite: 1219 passed (up from 1211 pre-session), run after the perf fix landed.
- Dashboard-specific suites re-run clean after the CSS cleanup pass.
