# 2026-08-28: Four new league-wide panels (fpl.page screenshot comparison)

Direct continuation: the user sent 7 real fpl.page screenshots (Price Changes, Team Odds, Odds
Tracker, Statistics, Top Transfers, Injuries, Expected Data) and asked "the screenshots should
show everything... whats missing."

## Gap assessment

Compared each screenshot against what already existed. Four were buildable immediately with data
this project already has, real and synced, with zero new backend work:

- **Injuries** — `models.availability.list_availability` already existed, already tested, already
  used by the squad-scoped Risk Monitor - just never surfaced as its own league-wide panel.
- **Expected Data** (xG/xA/xGI) — real current-season Understat data already sits in
  `player_match_stats_history` (the same table `fpl backfill-xg` populates and
  `player_regression.py` already reads). Deliberately built against THIS table, not
  `player_season_history` - checked live and confirmed `player_season_history` has zero rows for
  the in-progress 2026/27 season (it only gets written at season-boundary sync), so reading it
  here would have silently shown last season's stale numbers under a "current" label. xGC
  (expected goals conceded) is honestly omitted - it's a team-defensive stat needing match-
  participation-weighted team xG-against, not a column available per-player at this grain.
- **Team Odds** — real per-team next-fixture clean-sheet %/projected goals, already computed by
  `_cached_fixture_goals_for`/`clean_sheet_probability` for the existing Fixture Tool/Fixture
  Projections panels, just re-ranked into fpl.page's own list shape instead of a per-fixture grid.
- **Top Transfers In/Out** — real per-player net transfer counts already tracked in
  `player_transfer_momentum_history` (the same table the squad-scoped Market momentum panel
  already reads), unfiltered and split by direction.

Two genuinely need more than a re-skin, deliberately NOT attempted this session (disclosed, not
silently dropped):

- **Price Changes' rich UI** (search/position/team filters, player-photo toggle, a real per-hour
  trend % and progress-to-threshold bar) - the underlying price-prediction data exists
  (`_price_predictions_html`), but the filterable/searchable table chrome and the specific
  "progress toward the real FPL price-change threshold" metric are real UI/calculation work
  beyond a data re-skin.
- **Odds Tracker's live line chart** ("Biggest Movers," a time-series of odds moving over hours)
  - this project's `fixture_odds_live` table stores only the current snapshot per fixture, not a
  history of samples over time. Building this for real would mean adding periodic odds
  snapshotting into a new history table first - a real, if modest, backend addition, not a
  frontend-only task, and out of scope for this pass.

## New modules

`injuries.py::render_injuries_html` (crest, name/team, status/news text, chance-of-playing %,
last-updated), `player_data.py::render_expected_data_html` (sortable-by-xGI table, xG/xA/xGI
totals + per-90), `market.py::render_team_odds_html`/`render_top_transfers_html` (added to the
existing Market workspace). All reuse `_bulk_player_lookup`/`_official_badge_url`/
`_official_shirt_url` - every new row carries a real crest, continuing the same "more football,
more crests" work from the prior visual-density pass.

## Testing

5 new tests (`test_dashboard_workspaces.py`) covering each new panel's honest empty state plus one
real-data render (an injured player actually appearing). Full suite: 1024/1024. Live-verified
against the real production DB via the Claude Browser tool - all four panels render with real
crests/names/numbers, zero console errors. (One transient stale-browser-tab display, not a real
bug, caught and ruled out by diffing the actual `dashboard.html` file content against what the
tab was showing - the file was correct throughout.)
