<!-- Moved from CLAUDE.md during the 2026-08-27 documentation cleanup pass. Full session narrative, kept verbatim for reference - not required reading for day-to-day work. See docs/PROJECT_STATE.md for current state. -->

## Data model / logic (Pillar 2 Plan 2a — Tier 2-4 journalism connector)

- `news_items`/`news_item_players`/`news_item_teams` (migration `0013`) — the first
  Tier 2-4 (`strong_reporter`) source this project has ever ingested; everything
  before this was Tier 1 (official FPL API). FACTS only: a row is "this article
  exists, says this, as of this time," never a classified status change - it does
  not feed `change_events` or `players.status`.
- `ingestion/news_source.py` — BBC Sport Premier League RSS
  (`https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml`), parsed with
  stdlib `xml.etree.ElementTree` (no new dependency). Idempotent on the feed's own
  guid. `match_players`/`match_teams` link articles to players/teams by
  case-insensitive name-substring matching (web_name/full team name first, falling
  back to second_name/short_name with a word-boundary guard on the latter) -
  explicitly documented as a best-effort heuristic index, not a confirmed
  identification, and never written into any table CLAUDE.md's Data Integrity
  section covers. **Live-verification method:** `match_players`/`match_teams`
  were called directly against real synced player/team data and real fetched
  BBC article text, not via a single unbroken `fpl sync-news` CLI run showing
  nonzero `players_linked`/`teams_linked` in its own output — that combination
  needs a pre-populated players/teams DB before the first `sync-news` run in a
  given environment, and this verification worktree's DB was empty on first run
  with no clean way to reset and retry (this project's own safety hook blocks
  unscoped DB deletes). The matching logic itself is genuinely verified against
  real data either way.
- `fpl sync-news [--limit N]` - opt-in, same mold as `sync-history`/`sync-eo`, not
  part of regular `fpl sync`. `fpl team-news [--limit N]` - prints recent articles
  with their matched players/teams inline for grep filtering, same pattern
  `fpl projections`/`fpl prices` already use.
- `team-news-monitor` skill - was deferred in Phase 6/9 pending a Tier 2-4 source,
  now built. Surfaces raw article text for Claude to read and judge; never asserts a
  fact from an article alone.
- `config/storage.yaml news_retention_days` (default 90) - `fpl cleanup` now prunes
  `news_items` older than this (cascading the two linkage tables), so an
  all-season sync schedule doesn't grow the DB unbounded. Rows with no
  `published_at` (a malformed feed item) are never pruned by this clause.
- **Deliberately out of scope, deferred to Plan 2b:** predicted lineups (no
  reliable free, no-signup source found in this session's research - the sole
  no-key option found is marked deprecated by its own listing) and the
  manager-change engine (needs a second source to corroborate against per
  CLAUDE.md's precedence policy - one journalism source alone isn't enough to
  build a corroboration detector around).
- Spec: `docs/superpowers/specs/2026-08-20-pillar2-plan2a-tier2-news-connector-design.md`.
  Plan: `docs/superpowers/plans/2026-08-20-pillar2-plan2a-tier2-news-connector.md`.

## Data model / logic (Preseason calibration: squad churn + cross-league priors)

Not a roadmap pillar - a direct accuracy hardening prompted by the user asking
explicitly how this project handles the still-open 2026-27 transfer window
(new signings with no PL history, squad churn shifting real team strength
before real matches exist to show it). Researched first (arxiv Glicko-2
"structural shock" framework, cross-league transfer-forecasting literature,
FPL-community xPoints methodology), then checked what's actually buildable
free with this project's real data sources - full design doc:
`docs/superpowers/specs/2026-08-20-preseason-calibration-design.md`.

- **`models/squad_churn.py::team_churn_ratio()`** - minutes-weighted fraction
  of a team's real last-season contributors (>=450 minutes, via
  `player_match_stats_history`) no longer registered there this season (via
  current `players`/`teams`), no new external source needed. Returns `None`
  (not `0.0`) when there's insufficient history to compute honestly - covers
  genuinely promoted teams cleanly (Coventry/Hull/Ipswich in the current
  pool: real, confirmed via direct DB check, not a bug - their whole squads
  have zero `player_season_history`, correctly absent from the Dixon-Coles
  fit entirely, same flat-average fallback as before). Wired into
  `expected_points.py::_shrink_for_squad_churn`, called right after the
  Dixon-Coles fit succeeds: discounts `dc_home`/`dc_away` toward flat
  `_LEAGUE_AVERAGE_GOALS` proportional to the average of both sides' churn
  ratios, capped at `_CHURN_SHRINK_CAP=0.4` (a team never loses more than 40%
  of its fitted signal even at total squad turnover). Explicitly an
  uncalibrated heuristic (same honesty posture as `price_forecast.py`) - no
  in-season 2026-27 evidence yet to fit the shrink strength against.
  Live-verified against the real synced pool: Coventry/Hull/Ipswich
  correctly return `None`; every other team returns a real ratio in a
  plausible 0.17-0.60 range (Sunderland lowest at 0.17 - a newly-promoted
  side keeping continuity from its promotion campaign; Man City highest at
  0.60, capped to 0.4 when applied). `fpl build-team` still runs clean
  post-wiring (GW1 total 59.32 -> 58.52, a small, credible shift).
- **`ingestion/cross_league_source.py::backfill_cross_league_priors()`** +
  `fpl backfill-cross-league [--season YYYY-YY]` - for a player with zero
  `player_season_history` AND zero `player_match_stats_history` this season
  (genuinely new to the English top flight, not just new to Understat's EPL
  coverage), searches Understat's other 5 top-league player lists
  (`La_liga`/`Bundesliga`/`Serie_A`/`Ligue_1`/`RFPL`) for a name match.
  Discovered live while building this that `getLeagueData`'s own `"players"`
  field already carries season-aggregate per-player stats
  (games/time/goals/xG/assists/xA/team_title) - confirmed by a real fetch,
  not assumed - so this needed no per-match backfill at all, just one cheap
  request per league. Real per-90 rates are scaled by a **league-quality
  factor** (ratio of the two leagues' minutes-weighted goals-per-90, both
  computed from real fetched data, not a fixed constant) - a documented
  crude heuristic, not a trained cross-league model (that's a real, further
  step beyond this free, from-scratch project's current scope). Stored in
  `player_cross_league_prior` (migration `0015`, one row per player,
  idempotent upsert). Wired into `expected_points.py::_player_match_rates`
  as a new fallback tier tried before the pure positional-average guess
  `season_shrunk_rate` falls through to when a player has no PL history at
  all - both goals and xA are taken from the same cross-league row together,
  never mixed component-by-component with the positional-average fallback.
  **Live-verified against the real Understat API and the real synced pool**:
  92 candidates checked, 14 real cross-league matches found, e.g. Fulham's
  Gonzalo (ex-Real Madrid, 0.59 goals/90 off 923 minutes) and Man City's
  Rulli (ex-Marseille, 0.0 goals/assists per 90 off 2610 minutes - a real
  goalkeeper, correctly near-zero, a genuine sanity-check pass, not a bug).
  Quality factors moved in the expected real-world direction: Bundesliga
  (traditionally higher-scoring than the EPL) discounted to ~0.83, Serie A
  (traditionally more defensive) boosted to ~1.12. `fpl build-team` still
  runs clean post-wiring.
- **Update, same day: Championship-level promoted-team calibration (Component
  B), originally scoped out of this pass, was in fact built later the same
  session (2026-08-20)** - see `models/promoted_team_calibration.py` and the
  "Closed 2026-08-20: promoted teams had zero PL history" bullet under "What's
  still genuinely limited" below for the full account (migration `0016`,
  empirical Championship->PL shift, live-verified real numbers). This
  paragraph is kept for the historical record of the original scoping
  decision, not because the gap is still open. Also checked and ruled out
  cleanly (not silently skipped) that same session: the-odds-api.com has no
  EPL outright/futures market at any tier
  (`has_outrights: false` for `soccer_epl`, confirmed live against the real
  `/v4/sports` endpoint with the project's own key; the only outright markets
  offered at all are NFL/NBA/MLB/NHL/NCAA/golf/politics/World Cup) - a
  market-based team-strength signal for the squad-churn problem is a dead
  end for this free source, not a gap in this implementation.

## Live-ops/reliability maturity (Pillar 3, started 2026-08-20)

Pillar 3 (per [[project-fpl-architecture-roadmap]]: "register the already-built-
but-inactive Task Scheduler job, add push-notification alert channel, wire
drift-detection off the backtest harness") had not been started until now.

- **Push-notification alert channels are built** - `alerts/engine.py` gains
  `TelegramNotifier`/`DiscordNotifier`/`CompositeNotifier`/`configured_notifiers()`,
  both genuinely free (Telegram Bot API and Discord webhooks have no cost),
  both already anticipated as `.env.example` placeholders since Phase 1 - this
  closes that out rather than introducing a new dependency. `configured_notifiers(conn)`
  always includes `TerminalNotifier` (the original, still-default channel - a
  deliberate user choice, section 84) and adds Telegram/Discord only when their
  env vars are genuinely set; both CLI call sites (`fpl alerts --deliver`,
  `fpl run-scheduled`) now use it instead of a hardcoded `TerminalNotifier()`.
  One down channel can't silently drop alerts on a channel that IS working -
  each network notifier catches its own delivery failure independently rather
  than letting one exception abort the whole batch. **Found and fixed the same
  secret-in-error-message leak class already caught once this project for
  `odds_live_source.py`**: Telegram's bot token lives in the request URL path,
  Discord's webhook URL IS the secret - both notifiers build their
  `source_health.last_error`/printed-warning messages from safe fields only
  (HTTP status code), never `str(exc)`, before it could ever ship, with a
  regression test proving the secret never appears in the persisted error.
  Live-verified: `fpl alerts` still runs clean, terminal-only, with the real
  synced DB and no push config present - zero regression to existing behavior.
- **Registered 2026-08-20, after the user was asked directly and said yes.**
  Not done unilaterally while working through a gap-closure list, per this
  project's own safety posture - the user was explicitly asked ("register it
  now?") once they described wanting continuous during-gameweek monitoring,
  not before. See the dedicated "Scheduler registered" section below for the
  two real bugs found running `setup_scheduler.ps1` for the first time ever
  (it had only been syntax-checked before, never executed end to end).
- **Deliberately not attempted: drift-detection off the backtest harness.**
  The real mechanism (comparing live in-season prediction accuracy against the
  backtest's historical baseline) has nothing to compare against yet - there
  are no finished 2026-27 gameweeks to measure live drift from. Building the
  machinery now would be exactly the kind of thing this project's own
  discipline warns against: code that can't be live-verified before shipping,
  same category as the EO-threshold gap. Revisit once real GW1+ results exist.

## Competitor-scope gap: defensive contribution points (closed 2026-08-20)

User asked to check this project's scope against real competitor FPL tools
specifically to find what they cover that this project doesn't, not just
re-audit internal gaps already tracked. Research surfaced Fantasy Football
Scout's "DefCon Data" feature - checked whether this project modeled the
underlying real FPL scoring rule at all: it didn't, at all, despite the raw
data already sitting unused in `player_season_history.defensive_contribution`.

- **Real rule, verified live against two independent sources** (this
  project's own synced `rules` table AND a fresh web check of the official
  rules): a DEF hitting 10+ combined clearances/blocks/interceptions/tackles
  (CBIT) in a single match, or a MID/FWD hitting 12+ of the same plus ball
  recoveries (CBIRT), earns a flat 2 points, capped at 2 - unchanged for
  2026-27. GKP not eligible (`scoring.defensive_contribution.GKP=0`).
- **`models/defensive_contribution.py`** - no new methodology, reuses two
  patterns already established elsewhere in this codebase: season-grain
  shrinkage-regressed per-90 action rate (`bonus_regression.py`'s exact
  shape - no source here carries match-level CBIT/CBIRT counts, Understat
  doesn't track tackles/clearances/interceptions at all, same reason bonus
  is season-grain) feeding a Poisson threshold-crossing probability
  (`models/blend.py::clean_sheet_probability`'s exact methodology, just
  P(actions >= threshold) instead of P(goals == 0)).
- Wired into `expected_points.py::_player_match_rates`/`_match_components`:
  a new `defcon` term added to the per-match points sum, weighted by
  `p_full` (not the blended partial-appearance fraction) - same reasoning
  already established for clean_sheet, a 10-12-action threshold needs a
  full match to plausibly reach.
- **Live-verified against the real synced pool, both mechanically and for
  real-world plausibility**: Caicedo (genuinely known for high tackle/
  interception volume as a defensive midfielder) shows ~28% chance of the
  12-action threshold per match; Gomes ~33%; Haaland (pure striker, minimal
  defensive involvement) correctly ~0%. `fpl build-team` runs clean - real
  DEF/MID players with genuine defensive volume moved up in projected xP
  (e.g. Gabriel 3.89 -> 4.68 xP), GW1 squad total 60.25 -> 62.37, a real,
  credible shift, not a discontinuity. 366/366 tests.
- **Other competitor-scope items surfaced by the same research, deliberately
  not chased at the time**: live in-play point/rank tracking during a match,
  and the official app's "projected bonus after 20 minutes" feature - both
  need a real-time live-match-event data feed (BPS-in-progress, live
  minutes). **Correction, 2026-08-20: this project DOES have Tier 1 access
  to exactly that feed** (`GET /api/event/{N}/live/`, FPL's own official
  API) - the "no access" framing above was wrong, not just outdated; see the
  dedicated "Live in-play bonus tracking" section below for what's now built
  (`fpl live-bonus`) and what's still genuinely a further step (full squad
  live-score/rank aggregation, not just per-match provisional bonus).

## Competitor-scope check: real journalist GW1 teams vs ours (2026-08-20)

User asked directly: what do current journalists/community tools (Fantasy Football
Scout, RotoWire, allaboutfpl, etc) pick for GW1 2026-27, and why doesn't our
squad look anything like it. Researched live (WebSearch), then ran `fpl
build-team` for real and compared. Consensus across every source checked:
Haaland is the near-unanimous captain ("nobody gets punished for this obvious
pick"), Bruno Fernandes is the standard backup armband, both are template
picks. Our squad (pre-fix) had **neither** - not as a deliberate differential
call, but because of two real, confirmed bugs, found by refusing to accept
"the optimizer said so" as an explanation and checking the arithmetic by hand.

- **Bug 1 - `optimise_squad`'s ILP objective had zero captain-multiplier
  awareness (`optimization/squad.py`).** It maximized plain Σxp over 15
  players under budget; the captain was picked afterward as whoever ended up
  highest-xp in the chosen squad. Real FPL scoring doubles the captain's
  points every week - a squad-construction objective that ignores this
  systematically undervalues explosive-ceiling premiums relative to price,
  since their raw xp has to "pay for itself" once instead of the ~2x it's
  actually worth on the manager's best week. Fixed by adding one extra binary
  variable per candidate (`cap_i <= x_i`, `Σcap_i == 1`) contributing one more
  copy of `xp` to the objective for whichever squad member it lands on - the
  same formulation public FPL squad-optimiser tools use. Left unconstrained to
  starters-only deliberately: the player receiving the bonus is by
  construction the single highest-xp squad member, who `pick_starting_xi`'s
  own greedy top-xp fill always starts anyway - verified true in practice,
  not just assumed.
- **Bug 2 - the CLI's headline "GW1 expected points" number was silently
  wrong (`cli/main.py::build_team`).** It printed `primary.result.total_xp`,
  a plain sum over the full 15-man squad at equal weight - bench included,
  captain not doubled. Real "how many points do we expect this GW" is the 11
  starters' median summed plus one extra copy of the captain's median. Fixed
  to compute that directly instead of reusing the ILP's internal bookkeeping
  field for a different purpose than it was designed for.
- **Bug 3, found while sanity-checking why Haaland still didn't make the
  squad after fixing 1+2 - `models/squad_churn.py`'s contributor query
  silently merged every unresolved Understat player-appearance in the league
  into one artificial per-team "contributor" via SQL's NULL-grouping
  behavior.** `player_match_stats_history.player_id` is NULL wherever the
  Understat name crosswalk never resolved (fringe/loan/departed players who
  never entered this season's `players` table) - confirmed live, 4222 of
  11490 rows (36.7%) across the whole table. `GROUP BY player_id` groups all
  NULLs into a single row, so dozens of genuinely separate,
  individually-sub-threshold cameo appearances summed together and blew past
  `MIN_CONTRIBUTOR_MINUTES=450` as one phantom "departed" contributor -
  regardless of whether any one of them was ever a real contributor. Verified
  by hand for Man City: a single NULL-id blob carried 21520 of the team's
  36733 total contributor-minutes, inflating the reported churn ratio to
  0.60 (the single highest in the pool, capped to the 0.4 shrink cap) when
  the real figure - Bobb's departure alone - is ~0.03. Fixed with
  `AND player_id IS NOT NULL` in the contributor query. **Recomputed churn
  ratios for all 20 teams post-fix: every value now falls in a plausible
  0.0-0.21 range** (was 0.0-0.60), a systemic improvement across the whole
  league's preseason calibration, not just Man City/Haaland.
- **Same-session proactive fix, not yet triggered but a real latent trap:**
  `ingestion/cross_league_source.py::_candidate_players` used
  `id NOT IN (SELECT ... WHERE season=?)` against the same NULL-contaminated
  table. SQL's `NOT IN` silently matches nothing at all (three-valued logic,
  not an error) if its subquery returns even one NULL. Harmless today only
  because 2026-27 has zero synced matches yet (the subquery is empty) - would
  have silently zeroed out every future `backfill-cross-league` candidate the
  moment in-season backfill produces its first unresolved row. Fixed
  defensively with `AND player_id IS NOT NULL` in both `NOT IN` subqueries
  before it could ever fire for real.
- **Live-verified end to end**, real synced 587-player pool, `fpl build-team`:
  GW1 total 54.66 (post reporting-fix, pre churn-fix) -> 59.61 (post
  churn-fix), Bruno Fernandes entered the squad as captain (matches
  journalist consensus's "next-best if not Haaland" pick exactly). 366/366
  tests pass throughout.
- **What this does NOT close, stated honestly rather than forced:** Haaland
  himself still isn't in the optimizer's squad even after both fixes.
  Verified this is the model's genuine optimum, not a residual bug - directly
  tested by forcing him into the ILP and re-solving: the forced-Haaland
  objective is measurably lower (70.55 vs 71.53 unforced) than leaving him
  out. His real per-90 production checks out fine by hand against his actual
  27-goal/8-assist prior season (component math lands within a few tenths of
  his 6.85 median), but at £15.5m - the single most expensive player in the
  game - his xp-per-cost (0.44) is genuinely below several cheaper options
  this squad already needed anyway (Fernandes 0.54, Semenyo 0.68). This is a
  real, known tension in FPL strategy: pure EV-per-cost optimization under a
  hard budget cap doesn't always agree with "the popular pick," and
  journalist "best team" articles are also shaped by template-safety and
  rank-variance-avoidance psychology ("nobody gets punished for the obvious
  pick") that a pure optimizer has no reason to weight. Not fabricating
  confidence either way - this is a legitimate, disclosed divergence, not
  silently glossed over.

## Competitor-scope check, part 2: double-gameweek captain armband value (2026-08-20)

Continuing the same research thread with the user's explicit next check: does
this project handle DGW/BGW effective captain value the way real tools do -
i.e. does a captain who has TWO fixtures in one gameweek get credited for
both matches (summed) before the 2x multiplier, the way real FPL scoring
actually works?

- **Confirmed real bug, `models/expected_points.py::expected_points()`.** Its
  documented contract deliberately AVERAGES fixture-level goals inputs over
  a window ("single-match expected points... not a multi-match total") -
  correct and unchanged for its `from_event=None` "next n_gw fixtures from
  right now" rolling-context-window callers (squad building, wildcard-value
  price context). But `optimization/captaincy.py::evaluate_captaincy` and
  `optimization/chips.py::_candidates` both call it with `from_event=<a
  specific event>` and always `n_gw=1`, to evaluate one exact candidate
  gameweek - and for a genuine double gameweek (2 fixtures sharing that
  event id), the averaging path collapsed both matches into one
  match-equivalent snapshot instead of summing them. Real FPL scoring sums
  a DGW player's two matches' points, then applies the captain's 2x on top
  of that sum - averaging instead of summing would make a DGW captain look
  no better than a single-fixture player, when a double gameweek captain
  pick is one of the best-known, most-discussed real strategic plays in the
  game (every competitor site covers it explicitly).
- **Fixed by branching only the `from_event is not None` path to sum
  `_match_components` per fixture instead of averaging.** Verified every
  real caller of `from_event` always passes `n_gw=1` targeting exactly one
  event (grepped, confirmed - `captaincy.py`/`chips.py`, nothing else), so
  this is a precise, contained fix, not a behavior change to the separate
  multi-GW context-window path. Single-fixture events (the overwhelming
  common case, and blank-gameweek fallback) fall through to the same
  averaging branch as before - summing one item equals averaging one item,
  zero behavior change there, confirmed live against the real GW1 pool
  (Haaland's `from_event=1` median: 6.85 before and after, GW1 has no
  doubles this season).
- **Live-verified as a genuine bug, not just reasoned about**: a real
  regression test (`test_from_event_sums_a_double_gameweek_instead_of_averaging`)
  was proven to fail against the pre-fix code first (3.42 vs the required
  >6.05, a clean ~2x understatement) before confirming it passes post-fix -
  the actual before/after numbers, not an assumption. 367/367 tests.
- **Not yet triggered live** - GW1 2026-27 has no double gameweeks (they
  typically arise mid-season from postponed/rescheduled fixtures), so this
  fix has no effect on any current recommendation. It's correctness
  infrastructure for whenever the season's first DGW/BGW actually appears,
  fixed proactively now rather than left as a landmine, per this project's
  "verify with a synthetic case now" standard rather than "wait for real
  data" where a synthetic case can genuinely prove the mechanism (unlike
  e.g. the EO-threshold recalibration gap, which structurally cannot be
  tested without real post-GW1 sample data).
- **Also checked, correctly not a gap**: bench boost's interaction with the
  DefCon scoring rule (bench players earn DefCon points too when boosted).
  `chips.py::bench_boost_value` sums `c.xp for c in xi.bench`, where each
  bench candidate's `.xp` already comes from the same `expected_points()`
  call that has carried the DefCon term since the DefCon closure earlier
  this session (`_match_components`) - no separate wiring needed, DefCon is
  already inside every xP number bench boost sums. Confirmed by reading the
  call chain, not assumed.

## Competitor-scope check, part 3: real gap identified, not yet built (2026-08-20)

Checked FPL Review's "Elite 1000" sample concept against this project's own
sampled EO (Plan 1c) per the user's research method. **Confirmed real,
substantial, structural gap - not a bug, and not built this session.**
FPL Review's Elite 1000 is a cohort of 1000 manager entries **pre-selected
before the season starts**, using multiple seasons of historical FPL
performance/rank data to identify managers likely to be genuinely skilled -
then tracked as a fixed panel all season (median Elite-1000 manager
historically finishes ~50-70k overall; a same-sized current-top-10k
reference group finishes ~250k - materially different, more genuinely
"elite" populations). This project's `ingestion/eo_sample.py` instead
stratifies across the CURRENT live standings' rank 1-10,000 each time it
samples - at GW1 specifically, current overall rank hasn't stabilized from
any real points yet, so this is closer to an arbitrary cross-section than a
skill-selected one. These are genuinely different methodologies, not the
same thing under different names.

Replicating the real Elite-1000 concept needs a new capability this project
doesn't have: identifying a historically-consistent top-performing manager
cohort (fetchable free via FPL's own API - last season's final classic
`leagues-classic/314/standings/` gives real historical entry ranks, no paid
source needed) and persisting it as a stable panel to sample from instead of
re-stratifying live standings every time. This is a genuinely new,
non-trivial capability (a new data pipeline + selection methodology + its
own design decisions about how many seasons/what skill threshold to use),
not a quick fix to the existing sampler - and, like the EO threshold
recalibration gap, its output can't be meaningfully validated until real
in-season data exists to check the sample's predictive value against.
**Not built this session** - flagged honestly as a real, disclosed
next-roadmap candidate (a Pillar 2/3 follow-up plan) rather than either
ignored or rushed into a shallow, unvalidated version.

## Major correction: the backtest's "beats naive baseline" claim was largely vacuous (2026-08-20)

Found while researching real competitor architecture (see the OpenFPL comparison
below) and deciding whether to check our own model's accuracy on a specific
real-return bucket. Cross-checking that analysis surfaced the most severe bug
found this session - **the round-level walk-forward backtest has been silently
measuring almost nothing since Pillar 0 first shipped (2026-08-15).**

- **Root cause**: `rules` is only ever populated for the CURRENT live season by
  `fpl_api_bootstrap` sync (FPL's own API has no historical-rules endpoint) -
  it never had rows for any past season. `backtesting/harness.py`'s
  `_scoring_rates()` silently defaulted `scoring.goals_scored.{position}` and
  `scoring.assists` to `0` whenever a season's rules weren't found - which was
  every historical season ever backtested, including the "2025-26, MAE 0.4112
  vs naive baseline 0.4152, beats naive baseline" result reported earlier this
  session and treated as proof the shrinkage-regressed goals/assists engine
  works. Since the SAME broken zero-rate was applied identically to both the
  predicted side and the reconstructed-actual side, goals and assists
  cancelled out of the comparison entirely - the reported MAE gap was actually
  measuring almost nothing but card-rate shrinkage quality (appearance points
  are identical on both sides too, by the harness's own design). **Confirmed
  live, not just reasoned about**: a real 2025-26 match row (Gakpo, MID, 90
  minutes, 1 real goal) reconstructed to `2.0` points via the broken path
  instead of the real `7.0`.
- **Fixed two ways.** (1) `_scoring_rates()` now fails loudly (`ValueError`)
  instead of silently defaulting when a season's scoring rules aren't seeded -
  this class of silent corruption can't recur invisibly for any future
  backtested season. (2) `migrations/0017_historical_scoring_rules_2025_26.sql`
  seeds the real, sourced 2025-26 values (verified against Fantasy Football
  Scout's official rules explainer, fetched 2026-08-20 - the position-
  differentiated goal-scoring table introduced alongside DefCon in the 2025-26
  rule overhaul, unchanged into 2026-27) with `source='tier2_ffs_reconstructed'`,
  explicitly disclosed as a Tier-2 reconstruction, never conflated with a real
  `fpl_api_bootstrap` row.
- **This fix's own migration then exposed a second, independent, higher-severity
  bug already live in production**: `models/rules.py::current_season()` picked
  whichever `rules` row had the highest autoincrement `id`, not the row that
  actually reflects "what the live API most recently reported." The moment
  migration 0017 inserted historical 2025-26 rows (with a higher `id` than the
  already-synced 2026-27 rows), `current_season(conn)` started returning
  `'2025-26'` instead of `'2026-27'` **on the real production DB** - confirmed
  live before the fix. Every live command that reads budget/club-limit/
  free-transfer rules through it (`fpl build-team`, `transfers`, `squad`) would
  have silently used the wrong season's rule scope. Fixed by scoping the query
  to `source='fpl_api_bootstrap'` specifically - re-verified live afterward
  (`current_season()` correctly returns `'2026-27'` again), and `fpl doctor`/
  `fpl build-team` re-run clean with byte-identical output to before the fix
  (zero behavioral regression to the live GW1 recommendation).
- **The real, corrected backtest result**: `fpl backtest --season 2025-26` -
  MAE **1.1776** vs naive baseline **1.2402**, still genuinely beats naive
  baseline (real goals/assists differentiation actually being measured this
  time, not cancelled out). The magnitude was wrong by roughly 3x before this
  fix (0.41 vs the real 1.18) and the improvement margin is now a more
  believable ~5% (was an artificially tight ~1%, itself a symptom of comparing
  two near-identical mostly-zeroed formulas). The core claim survives - the
  model genuinely beats a naive per-90 baseline - but every previously-reported
  absolute MAE/RMSE number from this session predating this fix should be
  read as invalid, not just imprecise.
- **Scope confirmed contained**: `score_bonus_regression`'s separate season-
  totals holdout doesn't use `_scoring_rates`/season-scoped rule lookups at all
  (bonus values are already real points, no rate conversion needed) - unaffected,
  its own reported 60.1% shrunk-win-rate result stands as originally reported.
  `score_differentials` shares `reconstruct_actual_points` but has never scored
  anything yet regardless (`insufficient_ownership_data=True` for every
  historical season) - moot until ownership backfill exists, but now correct
  when it eventually does. 371/371 tests (4 new regression tests added: two
  proving `current_season()`'s source-scoping live, one proving the loud-fail
  on an unseeded season, one confirming `get_rule()` itself stayed
  source-agnostic by design).
- **Lesson for this project, stated plainly**: this is the same class of miss
  as the Understat/backfill-xg incident and the live-odds bookmaker-index bug -
  a feature that looked completely fine through per-task review, whole-branch
  review, and every mocked test, because nothing in that review chain ever
  asked "does the ACTUAL NUMBER make sense" against a real, hand-computed
  example. Every one of this project's real, previously-undiscovered bugs
  found this session (Man Utd/Spurs, Understat scraper, the churn NULL-grouping
  bug, this one) was found the same way: pick one real row, compute the
  expected answer by hand, compare against what the code actually produced.

## Competitor architecture check: what "state of the art" actually looks like (2026-08-20)

Per the user's explicit ask to check the real level of competitor architecture
and surpass it, not just their feature scope. Researched real, disclosed
methodology (not just marketing pages) for FPL Review, LiveFPL, Fantasy
Football Scout, and a genuinely load-bearing find: **OpenFPL**
(arxiv 2508.09992, "An open-source forecasting method rivaling state-of-the-art
Fantasy Premier League services") - an academic paper that benchmarks itself
directly against a leading commercial FPL prediction service.

- **OpenFPL's real architecture**: position-specific ensemble gradient-boosted
  models (XGBoost + Random Forest, Optuna-tuned hyperparameters), trained on
  four prior seasons (2020-21 to 2023-24) of official FPL + Understat data,
  validated **prospectively** on a genuinely held-out season (2024-25) - not a
  retrospective in-sample fit. Its headline claim: accuracy comparable to a
  leading commercial service overall, and it **surpasses that commercial
  benchmark specifically for high-return players (>2 points)** - the tail
  cases that matter most for captaincy and rank-climbing differentials.
- **This project's architecture is structurally different**: `calibrated-v2`
  is a hand-built statistical/Bayesian system (Dixon-Coles Poisson team
  strength, empirical-Bayes shrinkage toward positional priors, an empirical
  minutes-bucket distribution, a devigged bookmaker-odds blend) - interpretable
  and individually well-tested, but not a learned ensemble, and its
  ceiling/floor bands are a hand-tuned multiplicative heuristic
  (`median * 1.8 + ...`) rather than something fit to real tail-outcome data.
  This is a genuine, disclosed architectural gap against the actual
  state-of-the-art approach, not just a feature-scope one.
- **Multi-season training data is genuinely feasible to build, checked
  before committing to anything**: `player_season_history` (official FPL
  career totals) already goes back to 2006/07 (2031 rows, already synced) -
  but the MATCH-GRAIN data an ML ensemble actually needs
  (`match_results_history`/`player_match_stats_history`, football-data.co.uk
  odds + Understat xG) is currently backfilled for **2025-26 only**. Extending
  to 3-4 more seasons uses the exact same already-built, already-live-verified
  `fpl backfill-odds`/`fpl backfill-xg` commands - no new data source needed.
  `xgboost` is installable (confirmed via `pip install --dry-run`, free/
  open-source, no new heavy transitive dependencies beyond already-present
  numpy/scipy) - real DB storage headroom confirmed too (~30MB current total
  vs the ~1-2GB approved budget).
- **Confirmed this project has the exact same weak spot, with real numbers,
  not just an assumption borrowed from the paper's abstract.** Bucketed the
  now-fixed 2025-26 backtest by real actual points (`<=2` vs `>2`, the same
  "high-return" threshold OpenFPL's paper uses): on **low-return rows
  (n=4804)** the model clearly beats naive, MAE 0.7474 vs baseline 0.8237. On
  **high-return rows (n=785, ~14% of the pool - real hauls, the ones that
  actually decide captaincy/differential value)**, the model's MAE is
  **3.8100, statistically tied with the naive baseline's 3.7895 - not a clear
  win**, with a strong systematic under-prediction bias (-3.81 mean signed
  error). This is real, disclosed, load-bearing evidence for prioritizing the
  ML-ensemble initiative below, not just citing an external paper's claim.
- **Not built this session - correctly scoped as its own initiative, not
  rushed.** A genuine ML-ensemble challenger model is comparable in size to
  Pillar 0 itself (new dependency, feature-engineering pipeline, a proper
  train/held-out-season validation matching OpenFPL's own prospective-testing
  discipline, and a real head-to-head comparison against `calibrated-v2` on
  the same held-out data before ever being promoted to the live default -
  never claim a win without genuine evidence, this project's own standing
  rule). Flagged as the highest-leverage next architectural initiative,
  proposed as its own brainstorm/spec/plan cycle rather than half-built
  under time pressure.

## ML-ensemble experiment: a rigorous negative result, and a small real win (2026-08-20)

Per the user's explicit directive to reach commercial-model-level accuracy
before the GW1 deadline, "be creative... don't destroy tokens." Backfilled
2021-22 through 2024-25 (via the existing, already-tested
`fpl backfill-odds`/`fpl backfill-xg` commands - no new ingestion code
needed; one transient Understat connection timeout mid-run, not a code bug,
fixed with a shell-level retry, all 4 seasons landed at 380/380 matches),
seeded their real scoring rules (migration `0018`, same verified-values
pattern as `0017`), and ran three independent, honest experiments testing
whether a genuine XGBoost ensemble (OpenFPL's own architecture) beats
`calibrated-v2`'s hand-tuned linear formula on this project's real data,
trained on 2021-22 to 2024-25 and evaluated on the SAME held-out 2025-26
season `calibrated-v2` was already scored on (MAE 1.1776, high-return MAE
3.8100 - see the backtest-correction section above).

- **Experiment 1 (same features, different model class)**: `models/ml_ensemble.py`
  trained on the exact same leakage-safe inputs the linear formula already
  uses (shrunk/raw per-90 rates, minutes-bucket probabilities, position,
  scoring-rate constants). Held-out result: MAE **1.1771** (calibrated-v2:
  1.1776 - a statistically meaningless difference), high-return MAE **3.8385**
  (calibrated-v2: 3.8100 - actually marginally worse). **A genuine tie, not a
  win** - the model class itself (linear vs gradient-boosted trees) isn't the
  bottleneck when both are limited to the same feature set.
- **Experiment 2 (added real fixture/opponent-strength signal)**: extended
  the feature set with team/opponent expected goals from a per-round Dixon-Coles
  fit (`models/team_strength_dc.py::load_matches_for_fitting`/`fit_dixon_coles`,
  already-built, already walk-forward-safe machinery - reused, not
  reimplemented; fit once per round via `_fit_round_dc_model`, not once per
  row, to keep this affordable) plus home/away. Held-out result: MAE
  **1.1802**, high-return MAE **3.7896** - still a tie with calibrated-v2 on
  both counts (within noise either direction). Feature importances confirmed
  `raw_goals_per90`/minutes-bucket probabilities still dominate; the new
  fixture features landed a modest 5-6% importance each, not the driving
  factor hoped for.
- **Experiment 3 (position-specific models, OpenFPL's actual structure)**:
  four separate models (GKP/DEF/MID/FWD) instead of one with position as a
  feature. Combined held-out MAE **1.1939** - slightly *worse* than the
  unified model, smaller per-position training sets (708-6905 rows) losing
  more than the position-specialization gained.
- **Conclusion, stated plainly rather than oversold**: three independently-
  designed, well-instrumented experiments all converge on the same answer -
  a generic gradient-boosted ensemble does not meaningfully beat this
  project's calibrated-v2 statistical model on the signal currently
  available to it. This is real, disclosed evidence against the
  "architecture gap" hypothesis this line of research started from (reading
  OpenFPL's abstract) - not proof no gap exists anywhere, but proof it isn't
  sitting in "swap the model class" the way it first looked. If commercial
  services genuinely outperform on high-return players the way OpenFPL's
  paper describes, the more likely explanation is richer/proprietary data
  (in-house tracking data, denser bookmaker markets, non-public team-news
  signal) rather than model architecture alone - this project's own
  `calibrated-v2`, given the same inputs, is already competitive with a
  genuine ML ensemble.
- **A "small real win" was found, then correctly retracted by its own
  cross-validation, not left standing.** A first pass blending calibrated-v2
  with the ML ensemble (simple weighted average) appeared to beat either
  alone - MAE 1.1726 at a 50/50 blend vs 1.1776 calibrated-v2-only - but that
  weight was chosen by inspecting results on the same 2025-26 held-out set
  being reported, an actual peek, not just a theoretical risk of one. Redone
  properly: the blend weight was chosen on a genuinely held-out 20% slice of
  the TRAINING data only (2021-22 to 2024-25, split before any weight was
  picked, 2025-26 never touched during selection) - the honest optimum
  found there is **w=1.0, i.e. no blend at all, pure ML**, monotonically
  best as ML weight increases on that validation slice. Applying that
  properly-chosen weight to the real 2025-26 test reproduces Experiment 2's
  already-reported numbers exactly (MAE 1.1802, high-return MAE 3.7896) -
  **no blend advantage survives proper validation**. The earlier 50/50
  figure was overfitting to the specific test set it was tuned against, not
  a real, generalizable effect. Recorded here specifically because this
  project's own discipline is to catch and correct an optimistic first
  result before it ships, not just when a bug is found - this is that same
  standard applied to a modeling claim rather than a code bug.
- **Decision, made directly per the user's standing authorization rather
  than left open**: **not integrated into the live `fpl build-team` pipeline
  before the GW1 deadline - and now for a cleaner, stronger reason than
  originally written here.** Once honestly cross-validated, there is no
  measured win to integrate at all (see the retraction above) - the ML
  ensemble ties calibrated-v2, full stop, on every variant tested. Two
  further reasons this stays a research finding rather than shipped code:
  (1) this whole comparison is scoped to calibrated-v2's "core" backtest
  formula (appearance+goals+assists+cards) - the actual LIVE
  `expected_points()` model is already more sophisticated (clean-sheet
  probability, bonus regression, DefCon, live odds blending), none of which
  this ML experiment was trained against, so there's no drop-in path even if
  it had won; (2) shipping a tied-at-best model into the pipeline that
  generates tonight's real recommendation would add real complexity and risk
  for zero measured benefit. The trained model/dataset artifacts are kept
  locally (`data/ml_ensemble_v1.joblib`, `data/ml_ensemble_v2_fixtures.joblib`,
  `data/ml_dataset_v2.npz` - gitignored, regenerable from
  `models/ml_ensemble.py` + the now-backfilled 5-season data, not committed
  as binary artifacts) in case a future session finds a genuinely different
  feature or richer data source worth testing against this same honest
  cross-validation bar - not as a "nearly there" starting point, since this
  pass found no real edge to build on.
- `models/ml_ensemble.py` + `tests/test_ml_ensemble.py` (3 tests, synthetic
  data - proves the walk-forward extraction/leakage-exclusion/training
  plumbing works correctly, not a real accuracy claim) are committed as
  real, tested, reusable infrastructure regardless of the integration
  decision above. `xgboost`/`scikit-learn` added to `pyproject.toml` (both
  free, open-source, no cost). 374/374 tests.

## Competitor-scope closure + a major squad-optimizer correctness fix (2026-08-20)

Per the user's explicit directive to match/beat FPL Review and FPL Copilot's
feature set. Researched both directly (FPL Review: Massive Data Model
projections, multi-week Team Planner/Solver, Elite 1000 tracking, Season
Review, customizable projections; FPL Copilot: Solver, xP, Chip Strategies,
Rate My Team, Minileagues) and closed the clearest concrete gap.

- **`fpl rate-team --squad <ids>`** (`optimization/rate_team.py`) - a genuine
  "Rate My Team" for any EXISTING 15-man squad (the user's own real team, or
  one drafted anywhere else), matching FPL Copilot's/Fantasy Football Hub's
  tool. Built from 100% already-tested machinery (build_player_pool,
  pick_starting_xi, optimise_squad, captaincy_report, differentials/traps/
  breakouts/template) - no new modelling. `efficiency_percent` is a real,
  non-fabricated score: this squad's real GW1 xP (11 starters + captain
  bonus) as a percentage of the best achievable squad's xP under the same
  budget - not an arbitrary invented 0-100 rating. Also validates real FPL
  squad-construction legality (position counts, club limit) and deduplicates
  a repeated id rather than rating a nonsensical double-counted squad. 4
  tests (`tests/test_rate_team.py`).
- **A real, high-severity squad-optimizer bug found live while testing
  `rate-team`, not while looking for one.** A manually-assembled legal squad
  scored HIGHER (58.3 real XI+captain xP) than `optimise_squad`'s own
  reported "optimal" squad (56.83) under the identical budget - mathematically
  impossible for a genuine optimum, so the ILP's objective had to be wrong
  for the metric that actually matters. Root cause: `optimise_squad`'s
  captain-aware objective (added earlier this session) still weighted all 15
  squad members equally, including the 4 who never play most weeks - so it
  happily built a stronger bench (~13.5 combined xp) instead of paying
  Bruno Fernandes's £12m premium (6.23 xp, higher than every one of that
  squad's own starters), because bench xp counted at full starter weight in
  the objective. Confirmed live by hand before fixing, not assumed.
- **Fixed with a proper joint squad+XI+captain MILP.** Added `s_i` (starter,
  `s_i <= x_i`) alongside the existing squad-membership (`x_i`) and captain
  (`cap_i <= s_i`) variables, formation-bound the same way `pick_starting_xi`'s
  own min/max-play constraints already are (so the ILP's internal XI choice
  and the actually-reported XI agree), and re-weighted the objective:
  starters and the captain bonus at full xp, bench contribution
  (`x_i - s_i`) at `_BENCH_WEIGHT = 0.1` - a disclosed heuristic (a bench
  player's real expected contribution is near their full xp only on the rare
  week they're autosubbed in or Bench Boost is played, not fit to real
  historical autosub-rate data this project doesn't have), not zero (a
  benched player still has genuine hedge value, just far below a starter's).
  378/378 tests, zero regressions to the existing test suite despite the
  significant rewrite.
- **Live-verified, same real data snapshot, before vs after**: real
  XI+captain total 56.83 -> **59.21** (+4.2%) under the identical £100m
  budget - Bruno Fernandes now correctly included and captained, the bench
  now genuinely minimal cheap fodder (three players at the exact £4.0m
  price floor) rather than expensive mid-tier depth, matching real expert
  FPL strategy (load the XI, use the bench purely as budget enablers) far
  more closely than the pre-fix behavior did. This is a real correctness
  fix to the actual live GW1 recommendation, not just an internal metric -
  `fpl build-team`'s own headline squad changed as a direct result.
- **What this doesn't cover yet, disclosed rather than silently claimed**:
  FPL Review's "hourly updated projections" (this project's scheduler is
  built but deliberately left unregistered - the user's own standing choice
  about starting a persistent background process, not something to flip
  unilaterally even under general dev authorization) and "customizable
  projections" (no user-tunable model-input knobs exist here - every number
  is computed from real data with no manual override surface). Both are
  real, legitimate gaps, not yet closed, named honestly rather than glossed
  over.

## Build status

Phased build with checkpoints (user preference — do not attempt the full spec unattended). **All 9 phases plus Pillar 0 (prediction accuracy core) and Pillar 1 Plans 1a, 1b, and 1c (multi-GW transfer search + price forecast; scenario engine + chip DP scheduling + `fpl season-sim`; sampled effective ownership) complete, and Pillar 2 Plan 2a (Tier 2-4 journalism connector).**

- [x] Phase 1 — Foundation (DB, migrations, storage governor, config, logging, doctor)
- [x] Phase 2 — FPL Core (players, clubs, fixtures, prices, ownership, rules/scoring via official API)
- [x] Phase 3 — Intelligence, Tier 1 subset (injury/availability, set pieces, change detection). Transfers/team-news/manager-changes deferred — see above.
- [x] Phase 4 — Models (team strength history, fixture difficulty, expected minutes, preseason-prior xP). See caveats above — uncalibrated until real match data exists.
- [x] Phase 5 — Optimisation (squad ILP, transfer/captaincy/chip logic). Chip scheduling is single-decision-point only, not season-long — see above.
- [x] Phase 6 — Claude Code layer (Skills, subagents, hooks). See project-root caveat above before assuming these are active in any given session.
- [x] Phase 7 — Live operations (resource-aware scheduler, deadline-aware cadence, terminal alerts). Windows-only; scheduled task built but not registered (user's choice) - see above.
- [x] Phase 8 — Reliability (decision journal, cleanup, backup/restore, E2E test). Two real bugs found and fixed during this phase - see above.
- [x] Phase 9 — First-team ready (`fpl build-team`, readiness gate, `fpl final-check`). Section 122's final test passed live end to end - see above.
- [x] Pillar 0 — Prediction accuracy core (Dixon-Coles/odds-blended, shrinkage-regressed,
  minutes-distribution `calibrated-v2` model + walk-forward backtest harness). Spec:
  `docs/superpowers/specs/2026-08-15-market-rivaling-architecture-design.md`. Plan:
  `docs/superpowers/plans/2026-08-15-prediction-accuracy-core.md` (14/14 tasks, full
  implementer+reviewer ledger in `.superpowers/sdd/2026-08-15-prediction-accuracy-core/progress.md`).
- [x] Pillar 1 Plan 1a — Multi-GW transfer search + price-change forecast
  (transfer-momentum sync, uncalibrated price-forecast heuristic, `search_transfer_sequences`
  beam search, `fpl transfers --search`). Spec:
  `docs/superpowers/specs/2026-08-15-market-rivaling-architecture-design.md`, Pillar 1
  section. Plan: `docs/superpowers/plans/2026-08-15-decision-intelligence-plan1a-transfer-search.md`
  (7/7 tasks, full implementer+reviewer ledger in
  `.superpowers/sdd/2026-08-15-decision-intelligence-plan1a-transfer-search/progress.md`).
- [x] Pillar 1 Plan 1b — Scenario engine + chip DP scheduling + `fpl season-sim`
  (Dixon-Coles Monte Carlo scenario sampling, DP chip-window scheduling with advisory
  hit-week recommendations, differential heuristic backtest extension). Spec:
  `docs/superpowers/specs/2026-08-15-market-rivaling-architecture-design.md`, Pillar 1
  section (design judgment calls in `docs/superpowers/specs/2026-08-16-decision-intelligence-plan1b-design.md`).
  Plan: `docs/superpowers/plans/2026-08-16-decision-intelligence-plan1b-scenario-chip-dp.md`
  (11/11 tasks, plus one whole-branch review fix wave — full implementer+reviewer ledger in
  `.superpowers/sdd/2026-08-16-decision-intelligence-plan1b-scenario-chip-dp/progress.md`).
  Sampled effective ownership was originally scoped into this plan but split out to its
  own **Plan 1c** (below) — functionally independent, nothing in Plan 1b's cluster
  consumed it, and it's now built.
- [x] Pillar 1 Plan 1c — Sampled effective ownership (rank-stratified sample of
  Overall-league manager picks, captain/triple-captain-weighted EO with a real margin of
  error, wired additively into `differentials`/`traps`/`template`/`breakouts`/`captaincy`).
  Spec: `docs/superpowers/specs/2026-08-15-market-rivaling-architecture-design.md`, Pillar 1
  section (design judgment calls in
  `docs/superpowers/specs/2026-08-16-decision-intelligence-plan1c-design.md`). Plan:
  `docs/superpowers/plans/2026-08-16-decision-intelligence-plan1c-sampled-eo.md`
  (11/11 code tasks + 1 live-verification task + this docs task = 13/13, full
  implementer+reviewer ledger in
  `.superpowers/sdd/2026-08-16-decision-intelligence-plan1c-sampled-eo/progress.md`).
- [x] Pillar 2 Plan 2a — Tier 2-4 journalism source connector (BBC Sport Premier
  League RSS, name-matched to players/teams, `fpl sync-news`/`fpl team-news`,
  `team-news-monitor` skill). Spec:
  `docs/superpowers/specs/2026-08-20-pillar2-plan2a-tier2-news-connector-design.md`.
  Plan: `docs/superpowers/plans/2026-08-20-pillar2-plan2a-tier2-news-connector.md`
  (8/8 tasks). Predicted lineups and the manager-change engine remain open —
  Plan 2b, pending a viable free source for the former and a second corroborating
  source for the latter.
- [x] Live pre-match odds feed (the-odds-api.com, opt-in via `ODDS_API_KEY`) -
  closes the "unreachable today" limitation from Pillar 0. Spec:
  `docs/superpowers/specs/2026-08-20-live-odds-feed-design.md`. Plan:
  `docs/superpowers/plans/2026-08-20-live-odds-feed.md` (7/7 tasks + 2 post-merge
  fixes found live-verifying against real GW1 data - see the limitations section
  above for what they were). Live-verified 2026-08-20: 10/10 GW1 fixtures matched
  and blended.
- [x] Preseason calibration: squad-churn-aware team strength + cross-league
  new-signing priors. Spec:
  `docs/superpowers/specs/2026-08-20-preseason-calibration-design.md`. Built:
  `models/squad_churn.py`, `ingestion/cross_league_source.py` +
  `fpl backfill-cross-league`, migration `0015`. Live-verified against the
  real Understat API and the real synced pool (14/92 real cross-league
  matches found; churn ratios in a plausible 0.17-0.60 range). Championship-
  level promoted-team calibration remains open, documented above as a real,
  scoped follow-up.
- [x] Fixed a real, previously-undiscovered Dixon-Coles gap for Man Utd/Spurs
  (name-crosswalk bug, invisible to `fpl backtest` by design) - found while
  researching the above. See "What's still genuinely limited" below.

