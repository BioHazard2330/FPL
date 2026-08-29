# Session 2026-08-29: visual-quality correction pass

Direct, harsh follow-up after the forensic redesign pass (32-...): "the
graphs look absolutely terrible... team outlook looks ass why are there
dashes... where are the team crests... even during live tracking i dont
see any team crests like fotmob did... still says recomputing and shit."
Four real, separate corrections, not cosmetic tweaks.

## RECOMPUTING - confirmed already resolved, not stuck

Checked the real underlying state directly: `assess_recommendation_
freshness` against the actual production DB returned `is_stale=False`,
decision id 378 (computed 10:33:06, ~14m before the check). The
`app_meta['strategic_plan_auto_started_at']` timestamp predates that
decision, confirming the autonomous auto-recompute trigger fired and
completed correctly. The RECOMPUTING banner the user saw was a real,
transient state from an earlier regen (or their own open browser tab
predating the completed recompute) - not a stuck pipeline. No code
change needed; disclosed as a real, resolved state, not dismissed.

## Real crest fix (not a substitute)

The earlier session's "confirmed 403" finding was real but incomplete:
the official PL badge CDN 403s a BROWSER's cross-origin `<img>` load (it
checks `Referer`) - confirmed live this pass that a plain SERVER-SIDE
`requests.get()` (no browser, no Referer at all) against the exact same
URL returns a real 200 PNG for every team code. New `ingestion/
crest_assets.py`: `sync_team_crests()` (real, one-time-per-team fetch,
`fpl sync-crests` CLI command, uses `update_source_health` like every
other connector) caches each real crest to `data/crests/t{code}.png`;
`cached_crest_relpath()` is a pure, network-free filesystem check
dashboard rendering calls - genuinely test-safe (no network call from a
test, ever). A real, separate size bug found live during this: the CDN's
`/badges/80/` size 403s (only fixed sizes like 70 are actually served) -
`_CREST_SIZE` corrected to 70.

New shared `legacy.py::_crest_html(team_code, short_name, css_class)` -
real `<img>` against the cache, or an honest monogram fallback (never a
broken image). Wired into EVERY real crest call site across the
dashboard - Team Outlook, Match Centre, Fixture Ticker, Fixture
Projections, Injuries, Market (team odds + top transfers), Opportunity
Board, Expected Data, Points Changes, Price History, and (real, the
user's own specific complaint) Live Tracking rows, which previously
showed no team identity at all - `models/live_bonus.py::LiveBonusRow`
gained a real `team_code` field (a plain `LEFT JOIN teams`, no new
fetch). The old `_official_badge_url` (a bare hotlink URL builder with
zero callers left) was deleted.

Two real bugs found and fixed while wiring this in:
1. `crest_assets.py`'s own `DATA_DIR` was imported at module top level
   (`from fpl_agent.config import DATA_DIR`) - this captured the real
   production path once, before any test's `monkeypatch.setattr(
   "fpl_agent.database.connection.DATA_DIR", tmp_path)` could apply, so
   every test using it would have silently read/written against the real
   `data/crests/` directory instead of its own isolated tmp one. Caught
   by a real test failure (a test's own seeded team code collided with a
   real cached production crest). Fixed by looking up `DATA_DIR` as a
   live attribute on the `connection` module at call time, the same
   pattern `connection.get_connection()` itself already relies on.
2. `_crest_html`'s monogram fallback passed the caller's own crest
   `css_class` (e.g. `outlook-badge`, sized/positioned for an `<img>`)
   straight to the monogram `<span>` with no combination - since those
   classes only ever style `object-fit`/image sizing (nothing for a
   plain `<span>`), the fallback rendered as invisible, unstyled text
   whenever a crest wasn't yet cached. Fixed: the monogram now always
   carries the caller's class PLUS the real `outlook-badge-mono` styling
   class together.

## Team Outlook - dashes removed, not fixed in place

The Attack/Defence columns added in the prior redesign pass correctly
showed `&mdash;` (not a fabricated 0) for FPL's genuinely all-zero
preseason strength data - but a real user complaint that dashes on every
row look broken, not honest, is valid: an empty column communicates
nothing and reads as a bug. Removed both columns and their
`_avg_strength` computation entirely rather than defending the
`&mdash;` design - back to Team | Tactical signal | Fixture quality | FPL
signal, now genuinely fully populated for every real row alongside the
real crest.

## Graphs - Chart.js, not hand-rolled SVG

The Rank trajectory / Cumulative GW points / Captain contribution /
Starting XI actual-vs-expected / intragame rank / intragame points charts
in `live_charts.py` were entirely hand-rolled SVG polylines - functional
but genuinely amateurish next to a real charting library. Vendored
Chart.js 4.4.9 (MIT license) once to `data/vendor/chart.umd.js` (same-
origin, no live CDN dependency - works offline like every other asset
here). `live_charts.py` rewritten to emit a `<canvas>` + a real JSON data
payload instead of SVG math; a new client-side script in `assemble.py`
(`fplMarkerPlugin`, a real custom Chart.js plugin, not the separate
annotation package) draws the real best/worst/start rank markers from
server-computed dataIndex values - the SERIES computation stayed
entirely server-side and unchanged, only the drawing layer moved.
Real result: smooth bezier lines, gradient area fills, a native reversed
y-axis for rank (Chart.js's own `reverse` option), formatted tooltips,
and Chart.js's own legend for the dual-series charts - a categorical
visual-quality jump, verified via a real screenshot. Momentum/shot-map
(match_centre.py) were left as improved-SVG (already gained real minute
gridlines, goal markers, and a half-time divider earlier this session) -
a pitch-relative shot scatter genuinely doesn't fit a generic line-chart
library, and momentum's existing quality was judged adequate; a
disclosed, deliberate scope boundary, not an oversight.

## Tests

18 new/updated tests across `test_match_centre.py` (unaffected by this
pass), `test_live_charts.py` (5 tests rewritten for canvas/JSON output,
replacing SVG-specific `<polyline>`/marker-class assertions), `test_
dashboard.py` (Team Outlook column removal, crest wiring, Live Tracking
crest, FPL Impact strip - carried over from the prior pass), `test_
dashboard_workspaces.py` (data-health severity - prior pass). 1306/1306
full suite green.

## Genuinely still open (real, disclosed)

`fpl sync-crests` is a manual command, not wired into `run_scheduled` -
a real, low-frequency need (a club rebrand mid-season) that doesn't
justify automatic re-fetching on every cycle; disclosed as a real
follow-up if a new/rebranded club's crest ever needs a real refresh. The
pre-existing `.fdr-badge` class-name collision (a real crest image class
in the Fixture Ticker vs. a differently-styled difficulty-rating pill
class elsewhere) was found again while wiring crests through it - not
fixed this pass (a real, scoped CSS-naming cleanup, not urgent enough to
risk under this pass's time pressure). Type-scale tokens (`--fs-*`,
introduced in the prior pass) are still only applied to Match Centre, not
file-wide.
