<!-- Moved from CLAUDE.md during the 2026-08-27 documentation cleanup pass. Full session narrative, kept verbatim for reference - not required reading for day-to-day work. See docs/PROJECT_STATE.md for current state. -->

## What's still genuinely limited (read before trusting output)

- **Bonus is no longer a naive last-season carryover, but it's still not a real BPS model, and
  the round-level backtest still can't score it at all.** `models/bonus_regression.py` (a Pillar 0
  addendum, spec `docs/superpowers/specs/2026-08-16-bonus-shrinkage-design.md`, plan
  `docs/superpowers/plans/2026-08-16-bonus-shrinkage-regression.md`) gives bonus the same
  `shrink_rate()` empirical-Bayes treatment goals/assists/cards already get, but
  over `player_season_history` SEASON TOTALS rather than per-match rows — no source this project
  has carries bonus/BPS at match granularity (BPS is FPL-proprietary; Understat doesn't have it),
  so it's a season-grain, leave-one-season-out treatment, not the match-grain `as_of_date`
  walk-forward the rest of `calibrated-v2` uses. `core_expected_points()` and the round-level
  `fpl backtest` still deliberately exclude bonus entirely: Understat's reconstructed "actual"
  side has no bonus field, so scoring a predicted bonus term against it would compare the model to
  information neither side can see, corrupting MAE/RMSE rather than making it more honest. Scored
  instead via a separate season-level holdout, `fpl backtest --bonus`
  (`score_bonus_regression`) — live-verified against a freshly synced player pool this session:
  328 players scored (381 had ≥2 seasons of bonus history in `player_season_history`; 53 dropped
  for a zero-minute held-out season), shrunk MAE 0.2052 vs naive (unshrunk, prior-season-only) MAE
  0.2228 — shrinkage wins on 60.1% of individual players. A real win on real data, but
  `PRIOR_STRENGTH_MATCHES = 10` is still the goals/assists/cards value carried over unmodified,
  not independently tuned for bonus — worth its own value as a follow-up, not something this
  result closes off. The 328-player holdout is smaller than the real live pool: against the
  actual synced 587-player pool, 83 players have zero `player_season_history` rows and 123 have
  exactly one — together ~35% of the pool that this holdout's evidence says nothing about (a
  leave-one-season-out holdout needs >=2 seasons per player to hold one out). Players with zero
  season history now get the pure positional-average prior instead of the old hard `0.0` fallback
  (see `expected_bonus_per90`) — a real behavior change for that ~14% of the pool that this
  holdout doesn't directly validate, though it's the same honest-fallback pattern used throughout
  this model layer (e.g. `shrink_rate`'s own zero-matches behavior), not a fabrication.
- **Live pre-match odds blending is reachable, opt-in, and live-verified against real
  GW1 data (2026-08-20, after the user configured their own free key).** `fixture_odds_live`
  (migration `0014`) + `ingestion/odds_live_source.py` (the-odds-api.com, free tier,
  no cost, ~500 credits/month, `h2h`+`totals` × 1 region = 2 credits per
  `fpl sync-live-odds` call covering every upcoming fixture in one request - ample
  for a full season) + `fpl sync-live-odds` populate real pre-match quotes, matched
  to FPL fixtures via the existing `market_identity` crosswalk.
  `models/expected_points.py::_fixture_odds_row` falls back to this table only when
  no historical (played-match) odds row exists for a fixture - the backtest/
  historical path is completely unaffected. Requires `ODDS_API_KEY` in `.env` (see
  `.env.example`) - without it, every projection degrades to Dixon-Coles-only
  exactly as before.

  **Two real bugs found and fixed during the first live run against real GW1 data,
  neither caught by mocked-payload testing:** (1) the-odds-api returns clubs' full
  names ("Manchester United") while FPL's own `teams.name` is the short display
  form ("Man Utd") - 6 of GW1's 10 fixtures failed to match until a local alias
  table (`_ODDS_API_TEAM_NAME_ALIASES`) was added to translate the known current
  divergences before the existing crosswalk runs. (2) `parse_live_odds_event`
  originally always took `bookmakers[0]` - live-verified that for every single GW1
  fixture, the first-listed UK bookmaker had only the `h2h` market priced this far
  from kickoff, while several later-listed bookmakers already had the `totals` line;
  since the blend requires the full 1X2+totals set, this meant the feature was a
  silent no-op end to end (odds fetched and matched correctly, but never actually
  blended) despite passing every mocked test. Now searches bookmakers for the first
  one with both markets complete, falling back to h2h-only (same single-bookmaker,
  not-averaged design, just not blindly index-0). Real, measured effect on the live
  pool: `fpl build-team`'s total GW1 xP moved 36.93 → 39.4 and the captain pick
  changed from a cheap defender to Arsenal's keeper, correctly reflecting Arsenal's
  real 1.17 home-win market odds against a big underdog - signal Dixon-Coles alone
  (fitted on prior-season results, blind to this specific market reaction) was
  underweighting. Both fixes are additive, don't touch the historical/backtest path,
  and are covered by regression tests reproducing the exact real failure observed.
- **Backtest baseline is historical-only.** `fpl backtest` proves the model against 2024-25-style
  historical seasons (once backfilled); it says nothing yet about live in-season accuracy —
  revisit once real 2026-27 GW1-5 results exist to compare against.
- **`fpl backfill-xg` was broken, now fixed and live-verified (2026-08-20) — history kept below
  because the incident revealed a real blast-radius gap worth remembering.** Discovered live during
  the bonus-shrinkage verification: Understat's league/match pages had stopped embedding the
  `datesData`/`rostersData` JSON blobs `understat_source.py::extract_json_var` used to parse out of a
  `<script>` tag — a direct fetch returned a normal 200 and an ~18KB page with zero data variables
  anywhere in it, a real site-structure change on Understat's end, not a bug in this project's original
  code. `player_match_stats_history` had zero rows reachable, confirmed total across every season.

  **What was missed at the time: the blast radius wasn't just the backtest metric — it silently zeroed
  goals/assists for every player in LIVE projections too.** `player_shrunk_rates()`'s goals/xa
  components and `player_share_of_team_xg()` are both 100% Understat-dependent; with the table empty,
  both a player's own rate AND the shrinkage prior collapsed to 0, so `shrink_rate(0, 0, 0) = 0` for
  literally every player regardless of real ability — not a conservative estimate, a complete silent
  loss of the single largest scoring component. Haaland projected 2.49 xP (should be ~6-7 given his
  real ~6.3-6.8/game season average) purely from this — caught only because the user compared the
  squad's total xP against real-world magnitudes and pushed back, not by any test or review.
  **First fixed with a fallback**: `models/player_regression.py::season_shrunk_rate()`/
  `season_position_average_per90()` (same empirical-Bayes machinery `bonus_regression.py` already
  established) fall back to `player_season_history` (official FPL data, no Understat dependency)
  whenever a player has zero Understat match rows — leakage-safe for the backtest (`before_season`
  threaded through, regression-tested). Live-verified: Haaland → 6.16 xP, `fpl build-team`'s GW1 total
  moved 39.4 → 57.22.

  **Then the actual scraper was fixed too, same session.** Inspecting the live page directly (fetched
  it, searched for every `var` declaration — none found) and then the site's own real network requests
  (via a real browser) showed Understat's frontend now calls two plain JSON endpoints instead of
  embedding data: `GET /getLeagueData/{league}/{start_year}` → `{teams, players, dates}` and
  `GET /getMatchData/{match_id}` → `{rosters, shots, tmpl}` — same underlying field shapes as the old
  embedded variables, with two real differences confirmed against live responses (`"minutes"` renamed
  `"time"`; roster entries carry `"team_id"` instead of a `"team"` name string, resolved from
  `getLeagueData`'s own `teams` dict). Both endpoints 404 without an `X-Requested-With: XMLHttpRequest`
  header (a lightweight AJAX gate, not real anti-bot fingerprinting — no browser-automation dependency
  needed). `understat_source.py` rewritten to hit these directly (`json.loads`, no more regex
  var-extraction). Hit the identical club-full-name-vs-FPL-short-name mismatch class the live-odds fix
  found the same session (`"Tottenham"`/`"Manchester United"` vs FPL's `"Spurs"`/`"Man Utd"`) —
  consolidated into a shared `market_identity.normalize_common_team_name()` used by both connectors
  instead of duplicating the alias table per-connector. **Live-verified**: `fpl backfill-xg --season
  2025-26` — 380 matches, 11490 player rows, Haaland's real totals (35 matches, 27 goals, 2979 minutes)
  match `player_season_history` almost exactly. `fpl backtest --season 2025-26` — genuinely restored:
  12 rounds, 5589 predictions scored (was 0), MAE 0.4112 vs naive baseline 0.4152, **beats naive
  baseline**. Bonus regression: 328 players, 60.1% win rate, consistent with the earlier result.

  **What this means for right now, stated plainly rather than oversold:** it does not further change
  live GW1 projections tonight — this is preseason, so no current-2026-27-season match data exists yet
  for the primary Understat path to use either way; live numbers still correctly come from the
  season-grain fallback above. This fix's real value is restoring the backtest's evidentiary validity
  (the model's "beats naive baseline" claim is provable again, not just asserted) and setting up the
  pipeline for in-season backfills once 2026-27 matches actually start, at which point the primary
  match-level path will upgrade live projections past the season-grain fallback automatically, no
  further code change needed.
- **Manager-change detection is now built (2026-08-20)** - `models/manager_change.py`,
  `fpl manager-changes [--days N]`. Unlocked by adding a second independent Tier 2-4
  source (Sky Sports RSS, `skysports.com/rss/11095`, confirmed live/free/no-key) alongside
  BBC Sport - `ingestion/news_source.py::NEWS_SOURCES`/`sync_all_news_sources`, `fpl sync-news`
  now syncs both. A signal only fires when 2+ DISTINCT sources each have a manager-change-
  keyword-matched article about the same team within the lookback window - the real
  corroboration bar this project's own Tier 2-4 precedence policy requires, not just "a
  keyword matched somewhere." Same restraint as `team-news-monitor`: never writes to
  `teams`/`players.status`/`change_events`, a heuristic index for a human/Claude to read
  and judge, never an asserted fact. Live-verified: `fpl sync-news` pulled 52 real items
  (32 BBC + 20 Sky Sports, both sources healthy in `source_health`); `fpl manager-changes`
  ran clean and correctly reported no corroborated signal (the honest real preseason state,
  not a bug). **Predicted lineups remain genuinely open** - re-researched this session
  (2026-08-20), same conclusion as Plan 2a: the one no-key option found
  (Apify's Premier League lineups scraper) is still marked deprecated by its own listing.
  **Re-checked a third time, same day** (per the user's "nothing remaining before
  deadline" directive): `starting11.com`'s "free, no signup" predicted lineups turned
  out to be a crowd-sourced prediction GAME (users submit their own guesses, scored
  against the real lineup afterward), not an algorithmic/editorial publisher - no API,
  no structured data, and zero predictions submitted yet this season (useless even if
  it were scrapable). Confirmed structurally blocked, not under-researched - revisit
  only if a genuinely new free source appears.
- **No real squad exists yet.** Nothing here has ever been run against the
  user's actual FPL team, because there isn't one - this is a from-scratch
  build. `fpl build-team` produces a genuine first-XV recommendation from the
  live player pool; whether the user actually acts on it is their call
  (section 83: recommend only, never auto-submit).
- **Closed 2026-08-20: scheduler now registered and confirmed live** (see the
  dedicated section above for the two real bugs its first-ever real run
  surfaced). `fpl run-scheduled` now genuinely runs every 60 minutes via
  Windows Task Scheduler - data no longer goes stale purely from nobody
  running `fpl sync` manually.
- **Price-change forecast has never been checked against a real price-change
  event.** `models/price_forecast.py`'s ±0.005 threshold is a documented starting
  point, not empirically fit — this is preseason, so no real FPL price rise/fall
  has happened yet to validate the heuristic against, in either direction.
  Revisit once real in-season price movements exist to compare predictions to.
- **Closed 2026-08-20: cards had no season-grain fallback.** `season_shrunk_rate`
  (the fallback used whenever current-season Understat data is empty, i.e. every
  player right now, preseason) is built over `player_season_history`, FPL's own
  official season-totals endpoint - which carries no cards field at all (confirmed
  against the schema), so cards silently fell all the way to the pure positional
  average for every player, unlike goals/assists which at least got a real personal
  signal from that same fallback. Closed by adding a PRIOR-season Understat
  match-level fallback specifically for cards (`expected_points.py`'s `_player_match_
  rates`, using `models.squad_churn.prior_season`): richer than a season total anyway
  (real per-match data), leakage-free for backtest by construction (an entirely
  earlier season's full data can't leak into the season being predicted). Live-
  verified against the real pool: Haaland's cards rate moved from the flat positional
  average to a real personal 0.0801/90 (plausible - he rarely gets booked).
- **Closed 2026-08-20: promoted teams had zero PL history to fit Dixon-Coles from
  at all.** Coventry/Hull/Ipswich (this season's genuinely promoted teams, confirmed
  via zero `player_season_history` for their entire squads) were completely absent
  from `team_strength_dc.py`'s fit, so every one of their fixtures silently degraded
  to flat `_LEAGUE_AVERAGE_GOALS` - a real data gap (not a bug, unlike the Man Utd/
  Spurs one above), but a closeable one. `models/promoted_team_calibration.py` fits
  Dixon-Coles separately on Championship (E1) results (migration `0016`,
  `secondary_division_match_results` - a table kept STRICTLY SEPARATE from
  `match_results_history` so the live PL fit can never be corrupted by a cross-
  division match, verified by a dedicated isolation test) and derives a real
  empirical Championship->PL translation (additive shift on the model's log-scale
  attack/defence coefficients, not a ratio) from actual historical promoted teams -
  discovered programmatically (any team present in both a recent Championship fit
  and the current PL fit's lookback window must have been promoted at that boundary),
  not hardcoded, so the same code works next season without editing team names.
  Wired into `expected_points.py::_get_or_fit_dc_model` as a strict additive-only
  augmentation: a team that already has a real PL fit is never touched (regression-
  tested for byte-identical equality), a team with no Championship data either gets
  nothing fabricated (keeps the existing flat-average fallback). Small calibration
  sample size (3 teams: Burnley/Leeds/Sunderland, this season's only available
  historical promoted-team data point) is a real, disclosed limitation, not hidden.
  **Live-verified, both the calibration and the real-world direction of the
  numbers**: attack shift ≈ -0.13 (harder to score a level up), defence shift ≈
  +0.71 in this model's sign convention (leakier defence a level up) - both match
  real football intuition, not just internally consistent math. Applied to the
  current pool: e.g. Coventry (home) vs Newcastle now projects 1.67 scored / 2.73
  conceded instead of a flat 1.3/1.3 - correctly reads as a real underdog, not an
  average team. `fpl build-team`/`fpl doctor` both still run clean post-wiring.
- **Closed 2026-08-20: scenario engine now samples bonus with real per-trial variance.**
  `_sample_player_trial_points`'s bonus term was `bonus90 * weight`, identical every
  trial for a given minutes bucket - now `rng.poisson(bonus90 * weight)`, the same
  honest mean-preserving discrete-count approximation already used here for assists
  (no source carries real per-trial bonus/BPS data to sample from - Poisson's mean
  still equals the shrinkage-regressed expectation exactly, only real variance around
  it is now added). Regression-tested (`test_bonus_is_sampled_with_real_variance_but_
  preserves_the_mean`): 20000-trial sample recovers the calibrated mean to within 0.05
  while showing genuine variance.
- **Closed 2026-08-20: chip *selection* inside `schedule_chips` is no longer
  event-invariant.** `expected_points()` gained an optional `from_event` parameter
  (existing callers unaffected - the `else` branch is byte-for-byte the prior code
  path) that targets a specific future gameweek's fixture(s) instead of always "next
  fixture from now", reusing `expected_points_window`'s existing from_event fixture-
  lookup pattern rather than duplicating floor/ceiling/confidence logic anywhere.
  `optimization/captaincy.py::evaluate_captaincy`/`optimization/chips.py::_candidates`
  both thread an optional `event` through to it. Regression-tested at the real
  wiring level, not just the pure function (this project's own repeated lesson):
  `test_bench_boost_trial_values_picks_a_different_bench_per_event`/
  `test_triple_captain_trial_values_picks_a_different_captain_per_event` prove a
  genuinely different bench/captain gets selected for two candidate gameweeks with
  different underlying fixtures, not just that the parameter is accepted.
- **Traps/breakouts/template backtest scoring is deferred, not built - and stays that
  way for two real, structural reasons, not lack of effort (re-assessed 2026-08-20).**
  (1) `player_ownership_history` has no historical backfill source (see the
  differential-backtest bullet below) - any historical-season backtest for these three
  would report `insufficient_ownership_data=True` regardless of how much scoring code
  exists, exactly like `score_differentials` already does. (2) `traps.py` specifically
  also reads `expected_minutes()`/availability classification/price history, none of
  which have an as-of-date-aware historical variant anywhere in this codebase (unlike
  the ownership/Understat/season-history paths `differentials.py` already threads
  `as_of_date` through) - building that is real, substantial,
  currently-unprovable new infrastructure (blocked on point 1 regardless), not a
  small extension. Revisit if a free historical FPL-ownership source is ever found.
- **Differential backtest has nothing to score against yet.** `fpl backtest
  --differentials` currently reports `insufficient_ownership_data=True` for any
  historical season, including 2024-25, because `player_ownership_history` is only
  populated going forward from live syncs — no historical ownership backfill source
  exists. This is the honest, designed result right now, not a bug (live-verified);
  it will only start reporting real `mean_delta_vs_template` numbers once the live
  2026-27 season's own ownership history accumulates across enough gameweeks.
  `score_differentials`'s actual scoring/delta logic (as opposed to this guard) also
  has no shipped test coverage yet — it was verified out-of-band by the reviewer with
  a standalone harness during Task 9, not by a committed test — worth adding one if
  this path is touched again.

  **Re-checked 2026-08-20, claim above was too strong - corrected.** The user
  surfaced `github.com/vaastav/Fantasy-Premier-League`; live-verified it for real
  (`data/{season}/gws/gw{N}.csv`, back to 2016-17, free, no key) - it DOES carry a
  real per-player-per-gameweek `selected` field, a genuine historical ownership
  signal that does not exist anywhere else this project has found. So "no historical
  ownership data exists at all" was wrong. What's still genuinely missing: `selected`
  is a raw COUNT, not FPL's `selected_by_percent` - reconstructing the real percent
  needs the total-registered-managers count for that exact historical gameweek, which
  grows substantially through a season (fastest early on) and isn't published
  anywhere in this source or found elsewhere free (checked `players_raw.csv`, the
  repo's own README, no total_players field). Using a rank-percentile proxy instead
  was considered and rejected: it would feed a uniformly-distributed rank into
  `MAX_OWNERSHIP_PERCENT`/`MIN_OWNERSHIP_PERCENT` thresholds calibrated for real
  ownership's heavily right-skewed shape - a scale mismatch that could produce a
  confidently wrong backtest number, worse than today's honest
  `insufficient_ownership_data=True` guard. User agreed (2026-08-20) not to chase
  this further for now - real progress (a genuine data source found), but the
  percent-reconstruction problem is unsolved, not silently worked around.
- **Sampled effective ownership is real, but bounded and preseason-unverified end-to-end.**
  `fpl sync-eo --event N` samples ~750 of the ~10,000 Overall-league managers (rank-stratified,
  not a full census) — `eo_percent` carries a real margin of error
  (`SampleEOEstimate.margin_of_error_pp`, 95% CI), tightest for high-owned players and widest for
  low-owned ones, never an exact figure. That margin is derived on read but not yet surfaced in
  any CLI output — nothing prints it today. EO only exists for events `sync-eo` has actually been run
  against — there's no historical/prior-season backfill, and a gameweek `sync-eo` hasn't touched
  falls back to raw `selected_by_percent` (`eo_source="raw"`/`"unavailable"` depending on the
  consumer, see above). Wired additively into `differentials`/`traps`/`template`/`breakouts`/
  `captaincy` - all five preserve their prior raw-ownership behavior when no sample exists.

  **Deferred live verification:** `fpl sync-eo --event 1` was verified on 2026-08-16 against the
  live FPL API to fail cleanly and fast (exit code 1, message: `sync-eo failed: event 1 has not
  locked yet (deadline still ahead) - picks aren't available`) because GW1's deadline
  (`2026-08-21T17:30:00Z`) had not yet passed — this is preseason, so picks/standings data
  genuinely isn't available yet from FPL's API. This is a calendar constraint, not a gap in this
  plan's testing: the event-lock validation itself is fully verified (fast-fails before issuing any
  of the hundreds of doomed per-manager network requests it would otherwise make).

  A genuine end-to-end `fpl sync-eo --event 1` run against real sampled ownership data has to wait
  until after GW1's deadline passes (2026-08-21). When the user next returns to the project after
  that date, run `fpl sync-eo --event 1` for real and confirm sane, non-degenerate output: real
  (non-zero, plausible) `sample_size`, plausible `eo_percent` values across sampled players, and
  `fpl doctor` / `fpl source-status` showing the `fpl_eo_sample` source as healthy. That is the
  actual live-verification step this pillar's testing bar requires — it just cannot happen inside a
  preseason session.

  **Re-checked live 2026-08-20 (not just assumed): genuinely still time-gated, not an engineering
  gap.** Fetched `bootstrap-static` for real - GW1's deadline is confirmed `2026-08-21T17:30:00Z`,
  and the real fetch timestamp that session was `2026-08-20T08:05:41Z` - about 33 hours short, not
  yet lockable no matter how much further work is done today. The same applies to the ownership-
  threshold recalibration above: it needs real post-GW1 sample data to fit against honestly, which
  doesn't exist yet either. Not fabricating a number to close either gap early - both close
  naturally and quickly (GW1 locks well within a day of whenever this is next read), not via more
  code.

- **Fixed 2026-08-20: Dixon-Coles team strength had silently never fitted real history for Man
  Utd or Spurs, since Pillar 0.** Found while researching season-transition/squad-churn handling
  (not reported by the user this time - caught by direct verification of `match_results_history`
  team coverage). Root cause: `ingestion/football_data_source.py` (the only ingester of
  `match_results_history`, football-data.co.uk's historical CSV) called `get_or_create_market_team`
  with the source's raw team name, never routing it through `market_identity.normalize_common_team_name`
  the way `odds_live_source.py`/`understat_source.py` already do. football-data.co.uk's own naming
  happens to already equal FPL's short display form for every club except two - "Man United" (not
  "Manchester United", the only variant the alias dict had a key for) and "Tottenham" (not "Tottenham
  Hotspur") - so this created two disconnected duplicate `market_teams` rows holding the real 38-match
  history each, never linked to the `fpl_team_id` the live prediction path (`expected_points.py`,
  source="fpl") always resolves through. `_blended_fixture_goals`'s own guard
  (`team_market_id in dc_model.teams`) degrades gracefully rather than crashing, which is exactly why
  this went undetected by every prior review and by `fpl backtest`: it silently returned flat
  `_LEAGUE_AVERAGE_GOALS` (1.3) for both clubs' attack AND defence, every fixture, since Pillar 0 -
  losing all Dixon-Coles clean-sheet/goals-conceded signal specifically for Man Utd and Spurs (as both
  the team and the opponent). `fpl backtest`'s MAE/RMSE could not have caught this: that harness
  explicitly excludes goals-conceded/clean-sheet from core scoring by design (see the harness
  docstring), so this bug was invisible to it regardless. **Fixed**: added the missing `"man united"`
  alias key and routed `football_data_source.py` through `normalize_common_team_name` like the other
  two connectors (`tests/test_football_data_source.py::test_football_data_team_names_resolve_to_the_same_market_team_as_fpl`
  regression-guards it). The live dev DB's existing 74 misrouted rows were repaired in place (remapped
  `home_team_id`/`away_team_id` off the two orphan ids onto the correct ones, no row duplication - `380`
  match rows before and after). **Live-verified**: before the fix, `9 in model.teams` / `14 in
  model.teams` was `False`/`False`; after, both `True`, with real fitted attack/defence (Man Utd
  defence -0.36, Spurs defence -0.21) replacing the flat 1.3 fallback - e.g. Man City (home) vs Man Utd
  (away) now projects 2.04/1.11 expected goals instead of a flat 1.3/1.3. `fpl build-team` still runs
  clean (GW1 total 59.32, in the same plausible range as the pre-fix 57.22 baseline - a small, credible
  shift, not a discontinuity). 308/308 tests. This is a real, previously-undiscovered accuracy gap for
  two specific, high-profile clubs, not a hypothetical one - worth remembering as a general lesson:
  `_blended_fixture_goals`'s missing-team fallback is honest in intent (degrade gracefully rather than
  crash) but exactly the kind of silent degradation this project's own Data Integrity section warns
  about when it isn't cross-checked against real per-team coverage.

## Cross-competition news coverage closed (2026-08-20)

User asked explicitly: injuries/news from Carabao Cup, Champions League, and
other side competitions need tracking too, not just Premier League news.
Checked first (not assumed): both existing Tier 2-4 sources
(`BBC_PL_RSS_URL`, `SKY_SPORTS_PL_RSS_URL`) are Premier-League-scoped feeds -
a Champions League or Carabao Cup story would only reach this project once
(if ever) it resurfaced in PL-specific coverage. Found and added a third,
genuinely distinct, live-confirmed source: `feeds.bbci.co.uk/sport/football/rss.xml`
(BBC's general football feed - all competitions, not just the Premier
League) - verified live before adding (real, dated 2026-08-20 content,
distinct from the PL-specific feed's items, not assumed to exist). Kept as
an ADDITIONAL third source rather than replacing either PL-specific one -
broadens competition coverage without diluting the PL-specific corroboration
signal `models/manager_change.py` depends on (still needs 2+ distinct
sources agreeing).

Two tests in `test_news_source_sync.py` hardcoded "2 sources" - fixed to key
off `len(NEWS_SOURCES)` instead, so they no longer need updating if a fourth
source is ever added. **Live-verified**: `fpl sync-news` now pulls 133 items
(up from 52 with two sources), 83 new, 53 players linked - and genuinely
carries real cross-competition content (a live Champions League draw
article), not just added noise. 378/378 tests.

Also confirmed, not just assumed: FPL's own official `players.status`/
`chance_of_playing_*` fields (this project's Tier 1 availability source,
`models/availability.py`) are competition-agnostic by construction - the
live API reflects a player's current fitness regardless of which competition
caused an injury, so a Carabao Cup or Champions League injury was already
correctly reflected here even before this news-coverage broadening; what was
genuinely missing was the Tier 2-4 *context* (why, expected return date,
severity) for an injury sustained outside the Premier League specifically -
which this fix closes.

**Press conferences, addressed honestly rather than promised as new scope**:
there is no distinct free source for structured press-conference transcripts
separate from general football journalism - a manager's presser quotes reach
the public exactly through outlets like BBC/Sky Sport's own match/team-news
articles (e.g. "Arteta confident Lewis-Skelly stays at Arsenal" is
press-conference-derived content already flowing through the existing
pipeline). The now-three-source news pipeline above IS the closest
available proxy to dedicated press-conference tracking a free-resources-only
project can reach - not a gap silently left open, a real architecture
boundary named plainly.

## Scheduler registered + two real bugs found doing it (2026-08-20)

Per the user's explicit "yes, register it" after being asked directly
(continuous during-gameweek monitoring needs the persistent background
process, not manual invocations - the one action category this project's
own safety posture always required an explicit human decision for, never a
unilateral one even under general dev authorization).

- **`scripts/setup_scheduler.ps1` had never actually been run end to end
  before this - "tested" meant syntax-checked, not executed.** Confirmed
  live: the first real run threw `Register-ScheduledTask : The task XML
  contains a value which is incorrectly formatted or out of range` on
  `-RepetitionDuration ([TimeSpan]::MaxValue)` (~10,675,199 days - outside
  what Task Scheduler's XML schema accepts), **then printed "Registered
  scheduled task..." anyway** - a non-terminating PowerShell error with no
  try/catch let the script fall through to its own success message while
  registering nothing. Verified via `Get-ScheduledTask` immediately after:
  task genuinely did not exist. Fixed both problems: replaced the invalid
  duration with `(New-TimeSpan -Days 3650)` (~10 years, comfortably valid),
  and wrapped the registration in `try/catch -ErrorAction Stop` so a real
  failure is reported as one, never silently swallowed. Re-run clean:
  `Get-ScheduledTask`/`fpl scheduler-status` both confirm the task is
  genuinely registered (`State=Ready`, real `NextRunTime`).
- **`fpl readiness`'s "Scheduler" row was a hardcoded string, not a real
  check - directly contradicting this file's own stated contract** (`monitoring/readiness.py`'s
  docstring: "Every check reflects real, live system state - no hardcoded
  'yes' for anything not actually verified this call"). Caught because the
  row kept reporting "not registered" immediately after the task genuinely
  was. Fixed by extracting the Task-Scheduler query `fpl scheduler-status`
  already ran into a shared, testable function
  (`scheduler/status.py::check_scheduler_registered()`), now used by both
  the CLI command and `readiness.py` - one real check, not a duplicated
  subprocess call and a hardcoded string that could drift out of sync with
  reality (exactly what happened). 4 new tests
  (`tests/test_scheduler_status.py`). 382/382 tests total.
- **Live state now**: `FPLAgentSync` task registered, runs `fpl run-scheduled`
  every 60 minutes (resource-aware defer check still applies - low disk or
  low+unplugged battery still skips a cycle, section 21-22, unchanged).
  `fpl scheduler-status`/`fpl readiness` both confirm it live. Unregister
  any time with `scripts/remove_scheduler.ps1` if this stops being wanted.

## Live in-play bonus tracking - a corrected limitation (2026-08-20)

The user relayed another AI's suggested script (fetch live match JSON from
`premierleague.com`, compute 3-2-1 bonus from raw clearances/blocks). Taken
seriously enough to verify rather than dismissed, and it led to a genuine
correction: this project had previously stated "no Tier 1 access to a
live-match-event feed" (Pillar 2/DefCon sections above) - **that was too
strong.** FPL's own official API has exactly this:
`GET /api/event/{N}/live/` (`fantasy.premierleague.com`, not the bare
`premierleague.com` domain the relayed script named - confirmed live,
200 OK, correct real schema, currently empty `elements` since GW1 hasn't
kicked off yet - the honest preseason state, not broken). The relayed
script also conflated two genuinely different things: BPS (a separate
proprietary FPL formula, already computed and returned directly in
`stats.bps`) and DefCon's raw CBIT/CBIRT action counts (a different,
newer scoring rule this project modeled separately in
`models/defensive_contribution.py`) - reconstructing bonus from raw
defensive actions would have been wrong twice over: unnecessary (FPL
already gives you `bps`) and conflated with the wrong rule.

- **`ingestion/fpl_api.py::fetch_event_live(event)`** - one new adapter
  method, same retry/health-tracking pattern as every other one here.
- **`models/live_bonus.py::compute_live_bonus()`** - groups live elements by
  fixture (`explain[].fixture` - a double-gameweek player is scored
  independently per match, matching real rules, not summed), excludes
  0-minute players (can't earn bonus), ranks by `bps` within each fixture,
  assigns provisional 3-2-1 bonus via `_assign_bonus()` implementing the
  REAL official tie rule: two players tied for the top BPS in a match both
  get 3, and the next-best player gets 1 - not 2, that slot is skipped
  entirely, not given to a third player. `confirmed_bonus` is `None` until
  FPL finalizes it (~a few hours post-match, when `stats.bonus` actually
  populates) - reported honestly as "not yet decided," never fabricated as
  zero.
- **`fpl live-bonus [--event N]`** - single-shot like every other command
  here (this project's own architectural convention: Claude-orchestrated
  batch commands, not a permanent background loop). For a live-refreshing
  terminal view during an actual match, the user's own shell loop around
  this single command (`while true; do fpl live-bonus; sleep 30; done`) is
  the right layer for that, not a Python `while True` baked into the CLI
  itself.
- **Cannot be fully live-verified yet - GW1 hasn't kicked off, so there is
  no real in-progress match to test the live numbers against.** Built and
  tested against the real, well-documented endpoint schema instead (8 tests
  covering the tie-rule's exact edge cases: clear ranking, 2-way and 3-way
  ties for first, a tie for second, fewer than 3 players, double-gameweek
  independent-per-fixture scoring, and the "0 bonus mid-match means
  unfinalized, not zero" distinction) - honestly disclosed as
  schema-verified, not yet outcome-verified, rather than claimed as fully
  proven. The moment a real match goes live, this becomes genuinely useful
  with zero further code changes needed.
- **What this closes, stated precisely**: real-time official BPS/provisional
  bonus during a LIVE or just-finished match - genuinely new capability,
  matching what LiveFPL/the official app show. What it does NOT close: full
  live in-play POINT/RANK tracking (total live score, overall rank
  movement) - that needs live per-player total_points aggregation across a
  whole squad plus live overall-rank context, a larger feature this specific
  endpoint enables but doesn't itself provide; a real, disclosed follow-up,
  not silently claimed as done. 390/390 tests.

## Local auto-refreshing dashboard (2026-08-20)

User asked directly: does Claude need to stay open, and is an
always-updating website possible? Checked the real constraint before
answering (loaded the `artifact-capabilities` skill rather than guessing):
a published Artifact page cannot read this project's local SQLite database
(no filesystem access from a sandboxed browser page) and has no capability
to autonomously fetch external data on a timer without a viewer action - a
publicly-hosted, always-fresh, no-Claude-open website is genuinely not
reachable with this project's local-first, free-resources-only architecture
without a real hosting change (likely paid, out of scope). Said so plainly
rather than overpromising a public site.

What IS real and already true: Claude does not need to stay open for data
to keep updating - the Windows Task Scheduler (registered earlier this
session) already refreshes the database every 60 minutes on its own.

- **`monitoring/dashboard.py::generate_dashboard_html()`** - a real, local
  HTML snapshot: recommended GW1 squad (reuses `generate_build_team_report`,
  the exact same function `fpl build-team` calls, not a separate model),
  availability risks, full `fpl readiness` check table, and source health -
  all pure reads of current DB state, no network calls. Auto-reloads itself
  every 5 minutes via `<meta http-equiv="refresh">` - open it once, leave
  the tab open, it shows whatever the last sync produced without any
  further action.
- **`fpl dashboard`** generates it on demand; **`fpl run-scheduled`** now
  regenerates it automatically every cycle (failure here is logged but never
  fails the sync itself - a dashboard-write problem must never block the
  actual data sync it depends on). Written to `data/dashboard.html`
  (gitignored - a generated, regenerable artifact, same category as the
  ML dataset/model files from earlier this session).
- **Two real bugs caught before/while shipping this, not after**: (1) the
  `dashboard` command's first-ever run crashed with `NameError:
  DASHBOARD_PATH is not defined` - a leftover reference to a variable name
  from before a mid-build refactor (a module-level constant became a
  per-call function specifically to avoid the exact DATA_DIR-captured-at-
  import-time bug this project already caught once in `cleanup.py`/
  `storage.py` - the refactor was right, one call site just didn't get
  updated). Fixed, and a dedicated CLI-level test added
  (`test_dashboard_cli_command_prints_the_real_written_path`) specifically
  because the OTHER tests here call `_write_dashboard()` directly and would
  never have exercised the command's own `click.echo` line where the bug
  actually was - verified live that this new test fails without the fix,
  not just that it passes with it. (2) `generate_dashboard_html` originally
  interpolated player names/news text (ultimately sourced from an external
  API) directly into HTML without escaping - a real XSS-shaped risk for a
  page opened in a real browser even though it's local-only; caught by its
  own test while writing it (`test_generate_dashboard_html_escapes_
  untrusted_text`), fixed with `html.escape()` before it ever shipped.
- 4 tests (`tests/test_dashboard.py`), 394/394 total. Live-verified against
  the real synced pool: real squad/captain, a genuinely long real
  availability-risk list (confirmed-unavailable/doubtful players plus
  players who've permanently transferred out or gone out on loan - the
  existing `models/availability.py::classify()` behavior, not new to this
  feature), all 12 real data sources reporting healthy.

## Dashboard visual redesign + live-watch push notifications (2026-08-20)

Per direct user feedback that the first dashboard read as "plain"/"AI-generated"
(a styled table dump), plus an explicit ask for excitement during live play
("do I get updates when my player scores?"). Both closed same session, ~21h
before the GW1 deadline.

- **`monitoring/dashboard.py::generate_dashboard_html()`** rewritten wholesale:
  a real pitch layout for "My Team" (position rows, captain/vice armband
  badges, bench separated below), an honest "Live Tracking" panel with three
  real states (pre-kickoff schedule / live scoreboard / post-match - never
  fabricates a score), a "Transfer News" panel over `list_recent_news`, a
  compact chip-based system-health strip (was two long plain tables), and a
  pulsing auto-refresh indicator. Styled per the `dataviz` skill's validated
  reference palette (`references/palette.md`) - fixed categorical hue order
  for GKP/DEF/MID/FWD identity, status colors reserved for OK/DEGRADED/MISSING,
  never color-alone (every chip carries a text label too). Availability risks
  now filters to the squad's own 15 players (was leaguewide) - a deliberate
  behavior change, more useful on a "My Team" page. Headline xP reuses the
  exact starters+captain-median formula `cli/main.py::build_team` already
  established (not `total_xp`, which would reintroduce the earlier documented
  bench/captain-weighting bug).
- **`generate_dashboard_html(conn, live_payload=None)`** takes an optional
  already-fetched live payload so it stays a pure, fully-testable function -
  no network call of its own. `cli/main.py::_maybe_fetch_live_payload()`
  decides whether to fetch: only when a squad fixture is genuinely
  `started=1 AND finished=0` for the reference event, so outside any live
  window (all of preseason, and most of any matchday) zero extra network
  traffic happens. Regression-tested (`test_write_dashboard_does_not_fetch_live_data_outside_a_live_window`).
- **`fpl live-watch [--squad ids] [--interval 75] [--max-hours 3] [--deliver/--no-deliver]`**
  - fast-polls FPL's official `/api/event/{N}/live/` endpoint (Tier 1, the
  same one `fpl live-bonus`/DefCon already use) and pushes a real notification
  the instant a tracked squad player's goals/assists/provisional-bonus
  increases or they're sent off, through the same `configured_notifiers()`
  Telegram/Discord/terminal channels `fpl alerts` already uses (repurposing
  the existing `Alert` dataclass as a generic notification carrier, not a new
  channel). `models/live_bonus.py::diff_live_rows()` is the pure diff core:
  an EMPTY previous-state dict means "first observation this session" and
  seeds the baseline with **zero** events - without this, starting a watch
  mid-match would fire a false "just scored!" alert for every goal a player
  already had before the watch began (regression-tested). A bonus decrease
  (BPS swings mid-match are real and common) never fires an event - nothing
  to celebrate about bonus going down. `LiveBonusRow` gained a `red_cards`
  field (additive, default 0 - existing callers/tests unaffected).
  Deliberately **not** registered with the Windows Task Scheduler and
  **not** a permanent loop baked silently into every CLI call - explicit,
  narrow exception to this project's own single-shot-command convention
  (see `fpl live-bonus`'s own docstring), justified because diffing needs
  in-process state across a ~75s cadence that would be far messier to
  persist/reconcile across ~80 separate single-shot invocations over a
  ~2-hour match window. User runs it themselves during a live gameweek.
  Stops automatically once every fixture in the reference gameweek is
  finished, hits `--max-hours`, or on Ctrl+C.
- **Cannot be outcome-verified yet** - same honest limitation `fpl live-bonus`
  already carries: GW1 hasn't kicked off, so there is no real in-progress
  match to watch. Built and tested against the real, documented endpoint
  schema and a synthetic two-poll goal sequence (proves the diff fires
  exactly once, not on the seed poll) - schema-verified, not yet
  outcome-verified. Becomes genuinely live the moment GW1 kicks off
  (2026-08-21T17:30 UTC deadline, kickoffs shortly after), zero further code
  needed.
- 16 new tests (7 `diff_live_rows`, 4 `fpl live-watch` CLI, 5 dashboard panel).
  409/409 total. Live-verified `fpl dashboard` against the real synced pool:
  real squad (captain B.Fernandes, GW1 59.2 xP - matches the previously
  documented 59.21 build-team figure), real pre-kickoff fixture schedule for
  the squad's own teams, real BBC/Sky news items, all system-health chips OK
  except the two already-documented standing DEGRADED rows (Transfers/Team
  news - Tier 1 only, user's own standing choice). Screenshot-reviewed in a
  real browser, not just asserted from HTML strings.

