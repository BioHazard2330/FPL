# Session 22 — 2026-08-29: fpl.page-parity P1 features

Continuation of the P1 product-gap audit (session 19) — the genuinely-unbuilt list from
`docs/PROJECT_STATE.md`'s "Next recommended work" item 13. Worked the first six items of
that list end to end (source → data → computation → UI → decision impact mapped before any
code, per standing instruction); item 7 (visual/typography QA at more breakpoints) and item 8
(dead CSS / generated-output cleanup) closed as a verification/cleanup pass at the end. No
subagent dispatch (standing project rule) — all work done directly in the main thread.

## 1. Points Changes (new capability)

fpl.page's "Points Changes" page is a post-match Bonus/DefCon revision ledger (verified live
against the real site: "Post-match revisions to Bonus Points and Def Cons"). Real, no-new-
pipeline source found: `player_stats_snapshot` already carries a hash-gated `bonus`/
`defensive_contribution`/`retrieved_at` row on every sync tick — no ingestion change needed.

Detection heuristic (`models/points_changes.py::detect_points_revisions`, documented,
disclosed, not FPL's real unpublished review-timing): a fixture's `kickoff_time` + 130min
(match length) + 30min settle buffer marks "presumed full time"; if a player's bonus/defcon
value differs between the first and last post-cutoff snapshot, AND those two snapshots are
≥2h apart (filters ordinary live-BPS settling, which completes within an hour in every real
GW1 case checked), it's a real revision. Live-verified against real production GW1 data: 0
bonus revisions, 8 real DEFCON revisions (Gabriel/Rice/Tzolis/Enciso/Adams/Grealish/Gvardiol/
Anderson, all raw-count corrections below their position's scoring threshold — genuinely zero
net points impact this GW, not a designed-to-show-something result).

Dashboard panel `monitoring/dashboard/points_changes.py` (squad players flagged), CLI
`fpl points-changes`. 5 new tests (`tests/test_points_changes.py`) covering the stable/
revision/gap-window/no-finished-event cases directly against a synthetic snapshot timeline.

## 2. Template Team + elite-manager context

fpl.page's Template Team = highest-owned XI by top managers. This project's real "elite
manager" signal is Pillar 1c's sampled top-~750-of-~10k-league effective ownership
(`models/effective_ownership.py`) — the historical `elite_manager_panel` table is real but
genuinely empty until a season ends (confirmed: 0 rows in production), so that table could not
honestly back this feature yet. `models/template.py::get_template` already computed a
per-position top-N by EO with a raw-ownership fallback; extended `TemplatePlayer` with a
`margin_of_error_pp` field (threaded from `SampleEOEstimate`, zero new computation) — this also
closes a separately-tracked known gap ("sampled-EO margin of error … derived but not yet
surfaced").

Rendered as a position-grouped pool (not a formation-constrained best-XI — this project has
never computed one, and presenting one would imply a selection the data doesn't support),
reusing the existing `.projected-tile`/`.projected-pos-row` shirt-tile CSS component instead of
inventing new widgets. Live-verified against production: currently renders the honest raw-
ownership fallback (`fpl sync-eo` has never been run this season, `player_sample_ownership_history`
is 0 rows) — the disclosed-fallback path itself is what's real right now, and it renders
correctly.

## 3. Price History

fpl.page's PRICE CHANGES page = a searchable/filterable predicted-change table (PLAYER/
STATUS/PRICE/PER HR/TREND/PROGRESS/PREDICTED) plus a separate confirmed-change history list.
Real, no-new-pipeline sources found: `player_price_history` is already a full change-tracked
table (633 real rows in production) and `models/price_forecast.py` already had a real,
documented RISE/FALL/STABLE heuristic — neither had ever been surfaced league-wide (the old
`_price_predictions_html` was squad-scoped only, deleted as part of this work, not left as a
duplicate).

Built `monitoring/dashboard/price_history.py`: a league-wide forecast table with client-side
search/position/direction filters (data attributes + vanilla JS, no second query — same
pattern the Fixture Tool already established) and a real PROGRESS bar (`momentum_ratio` as a %
of `price_forecast`'s own threshold — explicitly labeled as this project's own derived value,
never FPL's real unpublished formula), plus a real confirmed-change ledger read directly from
`player_price_history`'s `valid_from`/`valid_until` chain. `fpl.page`'s "PER HR" metric has no
real equivalent in this project's data (only per-event cumulative transfer counts, no hourly
granularity) — not fabricated; net-transfers-this-event is shown instead, honestly labeled.

## 4. News → decision-impact enrichment

The existing news panel already tagged items "your squad" via real player/team name matching.
Extended `_news_html` (now takes `captain_id`/`ta` — the same already-computed decision-layer
objects `assemble.py` already has in scope, never a second competing scan, per the standing
decision-engine rule) to also tag WHY a matched item matters: "your captain" when it matches
the locked squad's current captain, "flagged: recommended transfer OUT" / "transfer target"
when it matches `ta.chosen.candidate`'s out/in player. Live-verified against production: a
real Haaland headline correctly shows the "your captain" tag.

## 5. Fixture Tool interaction parity

Audited against fpl.page's own Fixture Ticker (range/metric/sort/filter already close to
parity from the 2026-08-27 redesign). Added a real "Show" control (Fixtures/Goals/CS%) that
swaps each cell's displayed value between the opponent short-name and the same already-computed
`xGF`/clean-sheet% numbers the hover tooltip already carried — zero new computation, matches
fpl.page's own explicit Goals/CS% tabs. `data-goals`/`data-cs` attributes added per cell,
client-side toggle (same button-group JS pattern as range/metric/sort/filter).

## 6. Responsive QA completion

Prior sessions verified 1280/375px only. Verified 1440/1024/768/360px this pass (real
localhost server, `document.body.scrollWidth` vs `window.innerWidth` checked at each width, not
DOM-text guessing): zero real page-level horizontal overflow at any width. Two elements
initially flagged by a naive per-element scan turned out to be intentional, already-correct
`overflow-x: auto` scroll containers (`.site-nav` — more links now that Template/Prices were
added — and `.fdr-grid`, the Fixture Ticker's own wide-row container), not bugs.

## 7. Dead CSS / generated-output cleanup

Scripted audit: extracted every `.class` selector from `_CSS`/`_CSS_WORKSPACE`, cross-checked
literal-string occurrence across the dashboard package, then filtered out false positives from
dynamically-constructed class names (`f"opp-card-{kind}"`-style — confirmed via a stem+quote/
brace regex, spot-checked against source). 26 confirmed-dead CSS rules removed (an old
pre-redesign `.hero-verdict-*`/`.hero-metric-*`/`.hero-strip-label`/`.hero-watch-label` subset,
`.confidence-pill-row/-good/-mid/-bad`, `.strategic-col-*`/`.strategic-horizon-current`/
`.strategic-note-agree`/`.strategic-primary-badge`/`-body`/`.strategic-path-grid`,
`.squad-state-heading`/`-switcher-label`/`-pos-label`/`-player-in`, `.decision-evidence-body`,
`.fx-shirt`) — each verified to have exactly one occurrence (its own definition) across the
whole package before removal, and the base/sibling selectors sharing the same rule block kept
untouched. Also removed 2 confirmed-orphaned dashboard functions (`_captain_points_suffix`,
`_next_gw_plan_html` — a pre-redesign Next-GW-Plan panel superseded by Home/Plan, called by
nothing except its own now-deleted tests) and their tests. Verified via `generate_dashboard_html`
import + the full dashboard test suite after every removal batch.

## Bugs found and fixed during this pass

- `assemble.py::generate_dashboard_html` — `cap_id` was only assigned inside the
  `if locked is not None:` block but read later unconditionally by the news-enrichment call this
  session added — `UnboundLocalError` whenever no squad is locked. Fixed with an explicit
  `cap_id = None` default before the branch. Caught immediately by the existing test suite (33
  failures) before ever reaching production.
- `tests/test_dashboard.py::test_dashboard_live_tracking_shows_no_defcon_badge_for_gkp` asserted
  the literal string "DefCon" doesn't appear ANYWHERE on the whole generated page — too broad an
  assertion now that the new Points Changes panel legitimately says "DefCon" in its own
  always-present static subtitle. Narrowed to call `_live_tracking_html` directly (the same
  pattern its sibling test in the same file already used), which is what the test actually meant
  to check.

## Verification

- 8 new/updated test files, ~25 new test cases, all green.
- Full suite: 1197 passed, 0 failed (the 1 failure in the first full run was the DefCon-badge
  test above, fixed before the final run).
- `fpl dashboard` regenerated against real production `data/fpl.db`; served over a real
  localhost HTTP server (never `file://`) and verified in the Claude Browser tool: zero console
  errors, all 6 new/changed panels render real production data (Points Changes matches the CLI
  output exactly), interactive JS (Fixture Tool Goals/CS% toggle, Price History search filter)
  verified working via direct DOM interaction, zero page-level horizontal overflow at
  1440/1024/768/360px.

## Genuine remaining gaps (not attempted, honestly scoped)

- Template Team's sampled-EO branch is unverified against a REAL sample this season (`fpl
  sync-eo` has never been run in production) — the raw-ownership fallback is what's genuinely
  live-verified; the sampled path is only unit-tested against synthetic data.
- Price History's "PER HR" metric (fpl.page's own real hourly-granularity figure) has no
  equivalent in this project's data — net-transfers-this-event is shown instead, honestly
  labeled, not a fabricated hourly rate.
- News decision-impact enrichment only covers captain/transfer-out/transfer-in — does not yet
  cross-reference chip timing or multi-GW plan steps beyond the current recommendation.
- A full unified single-view Market redesign, Player Inspector click-through redesign (WHY BUY/
  HOLD/SELL), and decision-outcome calibration remain unbuilt (pre-existing, unrelated to this
  pass, tracked in `PROJECT_STATE.md`).
