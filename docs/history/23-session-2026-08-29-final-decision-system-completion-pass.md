# Session 23 — 2026-08-29: final product + decision system completion pass

Direct user spec: "fpl.page-level product quality + our own optimizer + our football
intelligence + our automated live system." A large, explicit checklist covering live-state
architecture, decision-snapshot integrity, chip explainability, model/market/football/template
cross-checking, and the remaining fpl.page-parity surfaces. Audited the actual current product
first (per the spec's own Part A instruction) before changing anything - several of the spec's
premises turned out to already be solved by prior sessions; those are documented as verified,
not rebuilt, per the standing "don't reopen already-solved bugs without new evidence" rule.

## Audit findings: already solved, verified not rebuilt

- **"Eliminate multiple definitions of live" / no fake countdowns**: already done (2026-08-29,
  earlier same-day session). `<meta http-equiv="refresh">` is already non-primary (invisible,
  a slower catch-all - the comment in `assemble.py` says so explicitly). The SYSTEM LIVE strip
  is the real primary indicator, and every countdown already derives from
  `next_due_at - Date.now()` against real stored timestamps (`fmtAgo`/`fmtIn` in `assemble.py`'s
  own script block) - no `counter--` pattern exists anywhere in the codebase (grepped).
- **Live change feed**: already a real compact event stream (`#live-changes-feed`), built
  entirely from real snapshot fields (`recent_changes`, `recommendation.last_change`,
  `match_events`, `bonus_defcon` deltas), deduplicated by a stable key, capped at 8 entries.
- **Decision snapshot integrity / one canonical decision**: already architecturally guaranteed -
  `sd`/`ta`/`ca` are computed once per regen and threaded through Home/Plan/Squad/Advanced: no
  second competing scan exists. `RECOMPUTING`/`STALE` banners already surface a real mismatch
  rather than silently repairing it (`models/decision_freshness.py`).
- **Strategy families clustering**: already done (session 19's `build_diverse_paths`) - live-
  verified this pass against production: "5 real strategy options... Paths 1-5 are statistically
  equivalent - too close to call a single winner" / "2 more optimizer paths statistically
  indistinguishable from this strategy" are real, current copy on the Plan workspace.
- **Performance / burst coalescing**: `_maybe_trigger_strategic_plan_recompute` already fires at
  most once per `run_scheduled` cycle (an aggregate "has anything material changed since the
  last decision" check, not a per-event trigger) and is guarded by a real 15-minute overlap lock
  against a still-in-flight prior recompute. The fast ~25s live-match poll loop never calls it at
  all (only `run_scheduled`, on its own slower adaptive cadence, does). Multiple news/lineup
  events inside one cycle were already structurally impossible to fan out into multiple
  recomputes - verified by reading, not by adding new debounce logic.

## Built this pass (real, verified, tested)

1. **Per-module live-state completion**: SYSTEM LIVE strip gained real "News" (max real
   `last_success` across this project's own real news sources, already in `source_freshness` -
   client-side, no new server field) and "Projections" (the real core-sync timestamp
   `cadence.system.last_sync_at` already carried) fields, both ticking off real stored
   timestamps like every other field in the strip.
2. **Points Changes LIVE/EXPIRED status**: `models/points_changes.py::is_gw_locked` implements
   fpl.page's own real, published rule (verified live against their help article: "locked 1 hour
   after full time of the final match") - checks every real fixture in the event directly
   (deliberately not the bootstrap `events.finished` flag alone, same reasoning
   `gw_lifecycle.py` already established). fpl.page's third "Pending" state (Opta recorded a
   correction, FPL hasn't processed it yet) needs Opta's own raw pre-FPL feed - this project has
   no access to that, so it is NOT fabricated; every revision shown is, by construction, already
   a real "Live" (applied) change. Wired into `live_snapshot.json` (`points_changes` block, real
   revision count + lock status, reusing the exact same detection function the full panel uses)
   and the live-changes-feed (a new real revision during a session now appears as a feed entry).
3. **Chip strategy explainability**: `chips.py::schedule_chips`'s own real `ChipExplanation`
   (best_alternative_event/opportunity_cost/confidence - the DP's own real per-event trial
   medians, already computed and logged under the "season_sim" decision type) was never read by
   any dashboard panel before this. `_chip_strategy_html` now surfaces it: chip / current value /
   best alternative GW+value / timing edge / confidence, read-only (no live DP solve triggered
   by a dashboard regen).
4. **MODEL vs FOOTBALL/MARKET/TEMPLATE cross-check** (new): direct spec ask - "do not average,
   show AGREE or CONFLICT or DIVERGENCE, then WHY." `models/decision_fusion.py::
   captain_cross_check` is a pure synthesis/labeling layer over three ALREADY-computed real
   results (football: the same qualitative-signal read `compare_captain_views` uses; market: 
   `external_benchmark.compare_captain_pick` against Solio, already built, never surfaced outside
   Advanced before this; template: a new, honestly-narrow-scoped check - does the wider
   real highest-owned pool even include this captain pick, since this project has no real
   per-player captaincy-rate data to compare against). Rendered as a compact 3-tag row + WHY
   lines directly on the Home hero, right under the captain verdict - answers "is the model an
   outlier" in one glance instead of requiring three separate Advanced-drawer panels.
5. **Template Team overlap/differential**: real "N/15 of your squad are in the highest-owned
   pool," real "your biggest differential" (lowest-owned real squad member, sampled-EO-with-
   raw-fallback), real "highest-owned players you don't have" (top 3 by EO, excluding squad
   members) - all derived from data `get_template`/`get_all_sample_eo` already compute, one
   extra query for the squad's own ownership values.
6. **Gameweek Projections range control**: the Goals/Clean-Sheet-% grid rendered a fixed 5GW
   window; now renders the real max (8GW) server-side and exposes real 3/5/8GW client-side
   toggle buttons (same one-render-many-views pattern the Fixture Tool already established,
   `data-col-index` per cell/header, zero new queries).

## Genuinely not attempted this pass (real, disclosed, not fabricated)

- **fpl.page's "Pending" Points Changes state**: needs Opta's raw pre-FPL-processing feed -
  no access, documented above rather than faked.
- **Player Inspector's full BUY/HOLD/SELL/WATCH/REVIEW vocabulary**: the existing per-player
  inspector (squad pitch cards) already gives one coherent WHY/verdict (HOLD/WATCH/CONSIDER
  SELLING), narrower in scope (squad-only, so "BUY" doesn't apply there) - extending to the
  full 5-state vocabulary across both squad and non-squad (Opportunity Board) contexts is real,
  separate follow-up work, not done this pass.
- **Live rank/GW-points/squad-contribution/captain-contribution/actual-vs-expected time-series
  storage for intragame charts**: real, scoped, larger infrastructure work (a new history table
  + a write path off the live poll) - not started this pass; the existing 2 live charts
  (`monitoring/dashboard/live_charts.py`, rank + cumulative GW points, per-finished-GW grain)
  are unaffected and still real.
- **Fixture Ticker team-multiselect / rotation analysis**: rotation explicitly needs a real
  rotation-risk model this project doesn't have (checked: `minutes_distribution.py` gives a
  per-player probability distribution, not a team-level rotation-congestion signal) - not faked.
  Team multiselect (beyond the existing squad-only filter) not built this pass.
- **Intelligence editorial restructuring** (WHAT CHANGED/WHY IT MATTERS/FPL IMPACT/CONFIDENCE
  card format) and **News → Decision pipeline** (SOURCE → CLAIM → ENTITY → STATE CHANGE → MODEL
  IMPACT → DECISION IMPACT) beyond this pass's own captain/transfer news tags: both real,
  scoped, comparable in size to their own session - not attempted.
- **Full visual redesign pass** (data rows/dense tables/editorial summaries replacing any
  remaining card-wall areas): not attempted - the existing visual language (flat, semantic-
  color-only, shirt tiles/timeline/opportunity rows/data tables) was judged, on inspection, to
  already largely satisfy this rather than needing a rewrite; a dedicated visual audit against
  fresh fpl.page screenshots is real follow-up, not done this pass.

## Verification

- New/updated tests: `test_decision_fusion.py` (+4 cross-check cases), `test_points_changes.py`
  (+4 GW-lock cases), `test_live_snapshot.py` (+2 points-changes-block cases),
  `test_dashboard.py` (+1 chip-explanation case, +1 projections-range assertion),
  `test_dashboard_workspaces.py` (+3 cross-check-render cases, +1 template-overlap case).
- Full suite green (see commit for the exact count).
- Live-verified against real production `data/fpl.db` via a real localhost-served
  `dashboard.html` render in the Claude Browser tool.
