"""Calibrated expected-points model (Pillar 0, spec 2026-08-15-market-
rivaling-architecture-design.md). Replaces preseason-prior-v1's linear
heuristics component by component:

- Appearance points: real 0/1/2 step function driven by an empirical
  minutes-bucket distribution (models/minutes_distribution.py), not a
  linear proxy on a single expected-minutes number.
- Goals/assists: shrinkage-regressed per-90 rates from shot-level Understat
  data (models/player_regression.py), not last-season xG scaled by current
  minutes fraction. Goals are further scaled by the player's share of a
  fixture-level team-goals estimate that blends a fitted Dixon-Coles model
  with devigged bookmaker odds (models/team_strength_dc.py, models/blend.py)
  - when no odds exist for a fixture (common for future fixtures; the odds
    source is mainly historical/closing lines, not a live pre-match feed),
    the blend degrades gracefully to Dixon-Coles-only rather than crashing.
  player_share_of_team_xg returns an ACCUMULATED volume ratio (season xG over
  team season xG), which already embeds the player's own historical minutes
  fraction. It is therefore divided by that historical fraction here to
  recover a per-90-equivalent share before this fixture's minutes fraction is
  applied - otherwise minutes would be discounted twice, which under-projects
  rotation-risk players by exactly their historical minutes fraction.
- Clean-sheet and goals-conceded-band probabilities: read directly off the
  blended Poisson distribution, not a linear heuristic on fixture difficulty.
- Bonus: shrinkage-regressed per-90 rate (models/bonus_regression.py), same
  empirical-Bayes treatment as goals/assists/cards but over player_season_history
  (season TOTALS) rather than per-match Understat rows - no source this project
  has carries bonus/BPS at match granularity (BPS is FPL-proprietary; Understat
  doesn't have it). Still not a real BPS event model and still excluded from
  core_expected_points()/the walk-forward backtest (Understat's "actual" side
  has no bonus field to compare against - adding one to the predicted side only
  would corrupt that metric), but no longer a naive unshrunk single-season
  carryover with zero positional prior.
- Cards: historical per-90 yellow-card rate (shrinkage-regressed the same
  way as goals/assists, models/player_regression.py), applied flat across
  positions per FPL's own scoring rule. Red cards aren't separately modelled
  (rare enough, and already partially reflected via reduced minutes) - a
  known, documented scope limit, not a silent gap.
- Goals-conceded penalty (DEF/GKP, -1 per 2 conceded): read off the blended
  team defence Poisson distribution via models/blend.py's
  goals_conceded_band_probability, replacing v1's "not modelled at all".
- Floor/ceiling bands: unchanged multiplicative bands around the new
  (calibrated) median - the spec's Pillar 0 scope didn't require rebuilding
  these, only the components feeding the median.

Three interface notes, all deliberate:

- expected_points()'s `n_gw` keeps v1's semantics: it still returns a
  single-match estimate, but the fixture-level goals inputs are AVERAGED
  across the player's next `n_gw` unfinished fixtures rather than read off
  the very next one only. v1 did the same thing with fixture difficulty.
  This is what lets optimization/chips.py tell a wildcard (n_gw=5) apart
  from a free hit (n_gw=1). Use expected_points_window() for genuine
  multi-gameweek totals.
- Every number here is still a per-match estimate. Nothing in this module
  multiplies by fixture count except expected_points_window().
- expected_points()/expected_points_window() have locked public signatures
  and always run in "live" mode (all available data). Code that needs an
  as-of-a-past-date estimate - the walk-forward backtest harness - calls
  core_expected_points(conn, player_id, as_of_date=..., season=...), which
  takes the same player-layer components (appearance/goals/assists/cards) and
  omits the team blend (clean sheet / goals conceded) the harness doesn't
  reconstruct per historical match anyway. That path is leakage-free for the
  rates and for the empirical minutes distribution, but NOT on the
  minutes fallback path, which inherits expected_minutes()'s live-data reads;
  the returned `minutes_source` flags which path ran. See
  core_expected_points()'s own docstring - it states the boundary exactly.
"""

import sqlite3
from dataclasses import dataclass

import numpy as np

from fpl_agent.ingestion.cross_league_source import get_cross_league_prior
from fpl_agent.ingestion.market_identity import get_or_create_market_team
from fpl_agent.models.blend import (
    blend_fixture_goals,
    clean_sheet_probability,
    goals_conceded_band_probability,
    market_implied_fixture_goals,
)
from fpl_agent.models.bonus_regression import expected_bonus_per90
from fpl_agent.models.defensive_contribution import defcon_points_probability, expected_defcon_actions_per90
from fpl_agent.models.expected_minutes import expected_minutes
from fpl_agent.models.fixtures import _reference_event
from fpl_agent.models.minutes_distribution import (
    expected_appearance_points,
    minutes_bucket_probabilities,
)
from fpl_agent.models.odds_devig import devig_match_odds, devig_totals_odds
from fpl_agent.models.player_regression import (
    player_share_of_team_xg,
    player_shrunk_rates,
    season_shrunk_rate,
)
from fpl_agent.models.promoted_team_calibration import augment_model_with_promoted_teams
from fpl_agent.models.rules import current_season, get_rule
from fpl_agent.models.scenario_sampling import sample_fixture_scorelines, sample_player_trial_points
from fpl_agent.models.squad_churn import prior_season, team_churn_ratio
from fpl_agent.models.team_strength_dc import expected_goals as dc_expected_goals
from fpl_agent.models.team_strength_dc import fit_dixon_coles, load_matches_for_fitting

MODEL_VERSION = "calibrated-v2"

_CEILING_GOAL_UPSIDE = 4.0
_ROTATION_DAMPING_PER_EXTRA_MATCH = 0.9
_LEAGUE_AVERAGE_GOALS = 1.3  # used when there isn't enough history to fit Dixon-Coles yet
_MIN_MATCHES_TO_FIT_DC = 10
# Never discount more than this fraction of the fitted Dixon-Coles signal
# toward flat league-average, even for total squad turnover - an
# uncalibrated heuristic ceiling (see docs/superpowers/specs/2026-08-20-
# preseason-calibration-design.md), not fit to real data. A team with heavy
# squad churn still has real fixture context worth more than zero signal.
_CHURN_SHRINK_CAP = 0.4

# Keyed by (id(conn), as_of_date); the connection itself is stored alongside the
# model so its id() can't be recycled into a false cache hit after it's closed.
_dc_model_cache: dict[tuple[int, str], tuple[sqlite3.Connection, object]] = {}
_last_match_date_cache: dict[int, tuple[sqlite3.Connection, str | None]] = {}


def _fpl_team_name(conn: sqlite3.Connection, team_id: int) -> str:
    return conn.execute("SELECT name FROM teams WHERE id=?", (team_id,)).fetchone()["name"]


def _last_real_match_date(conn: sqlite3.Connection) -> str | None:
    """Cached per connection, same `(id(conn), ...)`-keyed, identity-checked
    pattern as `models/rules.py`/`position_average_per90` - a real, cheap
    aggregate (`MAX(match_date)`) that doesn't depend on which fixture is
    asking, called once per distinct as_of_date candidate by
    `_dc_fit_as_of_date` below. Invalidated by
    `invalidate_last_match_date_cache` whenever `match_results_history`
    actually gains a new row (wired into
    `ingestion/football_data_source.py::backfill_football_data`, the table's
    only writer)."""
    key = id(conn)
    cached = _last_match_date_cache.get(key)
    if cached is not None and cached[0] is conn:
        return cached[1]
    row = conn.execute("SELECT MAX(match_date) AS d FROM match_results_history").fetchone()
    result = row["d"] if row else None
    _last_match_date_cache[key] = (conn, result)
    return result


def invalidate_last_match_date_cache(conn: sqlite3.Connection) -> None:
    _last_match_date_cache.pop(id(conn), None)


def invalidate_dc_model_cache(conn: sqlite3.Connection) -> None:
    """Real pre-existing gap closed while adding the two caches above
    (`_last_match_date_cache`/`_dc_model_cache`'s own coarsening): neither
    cache had an invalidation hook before this - `_get_or_fit_dc_model`'s own
    docstring already disclosed that gap for `_dc_model_cache` alone
    ("not invalidated by new match ingestion"). Wired into
    `ingestion/football_data_source.py::backfill_football_data`, the sole
    writer of `match_results_history` (the table both caches key off)."""
    key = id(conn)
    _last_match_date_cache.pop(key, None)
    for cache_key in [k for k in _dc_model_cache if k[0] == key]:
        del _dc_model_cache[cache_key]


def _dc_fit_as_of_date(conn: sqlite3.Connection, as_of_date: str) -> str:
    """Coarsens the Dixon-Coles fit cutoff for a genuinely FUTURE (unplayed
    as of `as_of_date`) fixture to one shared boundary - the day after the
    last real result in `match_results_history` - instead of that fixture's
    own exact date. Real perf gap this closes (2026-08-21, "Dashboard regen
    performance" continuation item): profiled `fpl dashboard` at 19 separate
    real Dixon-Coles refits (~4.9s each, ~92s of a ~124s profiled total) for
    a 5-gameweek fixture ticker, one per distinct real calendar date the
    ticker's ~100 fixtures happened to fall on - all of them genuinely
    future/unplayed, so every one of those 19 fits is mathematically
    provable to be IDENTICAL, not merely close, to the others: shifting
    `as_of_date` shifts every candidate match's `days_since`
    (`team_strength_dc.py`'s time-decay input) by the SAME number of days,
    which rescales every match's decay weight by the same positive constant
    - a uniform positive rescaling of a weighted log-likelihood sum never
    changes its argmax (`sum(c*w_i*loglik_i)` and `sum(w_i*loglik_i)` share
    the same maximizer for any `c>0`). That proof only holds when the set of
    matches included in the fit is unchanged between the two candidate
    dates, which "genuinely future" guarantees directly: no real match can
    exist between the coarsened boundary and the fixture's own date if the
    fixture itself hasn't been played yet. Falls back to `as_of_date`
    untouched whenever it is NOT strictly after the last real result
    (already-played/same-day fixtures, or no results synced at all) -
    correctness over speed there, and this is exactly why it lives inside
    `_get_or_fit_dc_model` as a cache-key transform rather than changing what
    any caller passes in: every caller (this module's own two call sites,
    plus `scenario_engine.py`) gets the collapsed cache key for free, and a
    caller genuinely asking about an already-played date is never affected.
    Deliberately does NOT touch `_fixture_odds_row`'s own date parameter
    anywhere - that lookup needs the fixture's real exact date to find its
    real odds row, an entirely separate concern from the DC-fit cutoff, and
    conflating the two would silently break odds matching for any fixture
    whose date differs from the coarsened boundary. Structurally unreachable
    from `backtesting/harness.py` (confirmed by grep, same as
    `_get_or_fit_dc_model` itself - that module never imports
    `expected_points.py` at all), so this has zero walk-forward leakage
    surface to guard against."""
    last_match_date = _last_real_match_date(conn)
    if last_match_date is None or as_of_date <= last_match_date:
        return as_of_date
    from datetime import date, timedelta
    y, m, d = (int(p) for p in last_match_date[:10].split("-"))
    coarse = (date(y, m, d) + timedelta(days=1)).isoformat()
    return min(coarse, as_of_date)


def _get_or_fit_dc_model(conn: sqlite3.Connection, as_of_date: str):
    """Cached per (connection, coarsened as_of_date) - refitting Dixon-Coles
    (a numerical optimization over every team) on every single player lookup
    would be needlessly slow; callers within the same backtest round or the
    same live prediction pass share one fit. `_dc_fit_as_of_date` collapses
    every genuinely-future `as_of_date` to one shared boundary before this
    cache is even consulted (see its own docstring for the correctness proof)
    - a live pass asking about several different future fixture dates in the
    same gameweek window now shares a single real fit instead of one each.
    The cache is not invalidated by new match ingestion, so a long-lived
    process that syncs mid-run would keep the older fit for an already-seen
    as_of_date.

    Only ever called from the live path (_blended_fixture_goals, in turn
    called by expected_points()/expected_points_window()/scenario_engine.py -
    never by core_expected_points()'s backtest path, which doesn't reconstruct
    the team blend at all, see this module's own docstring), so augmenting
    with current_season(conn)'s promoted-team calibration here is always
    correct - there is no historical-replay leakage risk to guard against."""
    as_of_date = _dc_fit_as_of_date(conn, as_of_date)
    key = (id(conn), as_of_date)
    cached = _dc_model_cache.get(key)
    if cached is not None:
        return cached[1]

    matches, team_ids = load_matches_for_fitting(conn, as_of_date)
    if len(matches) < _MIN_MATCHES_TO_FIT_DC or len(team_ids) < 2:
        model = None
    else:
        model = fit_dixon_coles(matches, team_ids)
        season = current_season(conn)
        if season is not None:
            model = augment_model_with_promoted_teams(conn, model, season)
    _dc_model_cache[key] = (conn, model)
    return model


# Every odds column is nullable in the schema, so require the full 1X2 +
# over/under set before devigging rather than trusting the ingester's
# current guarantee that 1X2 is always populated.
_ODDS_KEYS = ("home_win_odds", "draw_odds", "away_win_odds", "over_2_5_odds", "under_2_5_odds")


def _fixture_odds_row(
    conn: sqlite3.Connection, home_market_id: int, away_market_id: int, fixture_date: str, fixture_id: int
):
    """Odds for THIS fixture only - matched on the fixture's own date, never on
    "the most recent prior meeting". match_results_history holds played matches
    only, so a genuinely future fixture correctly finds nothing here and falls
    back to a live pre-match quote for this exact fixture (fixture_odds_live,
    populated by `fpl sync-live-odds`), rather than silently blending in a
    completely different match's closing line (e.g. last season's meeting
    between the same two clubs). If neither source has a row, the caller
    degrades to Dixon-Coles-only."""
    match_row = conn.execute(
        "SELECT id FROM match_results_history WHERE home_team_id=? AND away_team_id=? AND match_date=? "
        "ORDER BY id DESC LIMIT 1",
        (home_market_id, away_market_id, fixture_date),
    ).fetchone()
    if match_row is not None:
        row = conn.execute(
            "SELECT * FROM team_match_odds_history WHERE match_id=? ORDER BY retrieved_at DESC LIMIT 1",
            (match_row["id"],),
        ).fetchone()
        if row is not None:
            return row
    # No historical (played-match) odds row - fall back to a live pre-match quote
    # for this exact fixture, if one has been synced (fpl sync-live-odds).
    return conn.execute(
        "SELECT * FROM fixture_odds_live WHERE fixture_id=? ORDER BY retrieved_at DESC LIMIT 1",
        (fixture_id,),
    ).fetchone()


def _shrink_for_squad_churn(conn: sqlite3.Connection, dc_home: float, dc_away: float, home_row) -> tuple[float, float]:
    """Discount the fitted Dixon-Coles goals estimate toward flat league-
    average, proportional to how much of each side's contributing squad has
    turned over since last season - a real, computable signal
    (models/squad_churn.py) for how much to trust a stale historical fit
    before real matches this season re-earn that trust. A no-op when there's
    no churn data for either side (e.g. mid-season, when churn stops being
    the dominant source of team-strength uncertainty and match results
    speak for themselves)."""
    if home_row is None:
        return dc_home, dc_away
    season = current_season(conn)
    ratios = [
        r for r in (
            team_churn_ratio(conn, home_row["team_h"], season),
            team_churn_ratio(conn, home_row["team_a"], season),
        ) if r is not None
    ]
    if not ratios:
        return dc_home, dc_away
    shrink = min(sum(ratios) / len(ratios), _CHURN_SHRINK_CAP)
    if not shrink:
        return dc_home, dc_away
    return (
        dc_home * (1 - shrink) + _LEAGUE_AVERAGE_GOALS * shrink,
        dc_away * (1 - shrink) + _LEAGUE_AVERAGE_GOALS * shrink,
    )


def _blended_fixture_goals(
    conn: sqlite3.Connection, fixture_id: int, team_id: int, opponent_team_id: int, fixture_date: str
) -> tuple[float, float]:
    """(team expected goals, opponent expected goals) for one fixture.

    `fixture_date` is a plain YYYY-MM-DD date (not a kickoff timestamp): it is
    both the as-of cutoff for the Dixon-Coles fit (strictly-before, so a match
    played on the same day can't leak into its own prediction) and the exact
    key the fixture's own odds row is looked up by."""
    home_row = conn.execute("SELECT team_h, team_a FROM fixtures WHERE id=?", (fixture_id,)).fetchone()
    is_home = home_row is not None and home_row["team_h"] == team_id

    team_market_id = get_or_create_market_team(conn, "fpl", _fpl_team_name(conn, team_id))
    opp_market_id = get_or_create_market_team(conn, "fpl", _fpl_team_name(conn, opponent_team_id))

    home_id, away_id = (team_market_id, opp_market_id) if is_home else (opp_market_id, team_market_id)

    dc_model = _get_or_fit_dc_model(conn, fixture_date)
    if dc_model is not None and team_market_id in dc_model.teams and opp_market_id in dc_model.teams:
        dc_home, dc_away = dc_expected_goals(dc_model, home_id, away_id)
        dc_home, dc_away = _shrink_for_squad_churn(conn, dc_home, dc_away, home_row)
    else:
        dc_home = dc_away = _LEAGUE_AVERAGE_GOALS

    odds_row = _fixture_odds_row(conn, home_id, away_id, fixture_date, fixture_id)

    blended = None
    if odds_row is not None and all(odds_row[k] for k in _ODDS_KEYS):
        try:
            outcome = devig_match_odds(odds_row["home_win_odds"], odds_row["draw_odds"], odds_row["away_win_odds"])
            totals = devig_totals_odds(odds_row["over_2_5_odds"], odds_row["under_2_5_odds"])
            market = market_implied_fixture_goals(outcome, totals)
            blended = blend_fixture_goals(dc_home, dc_away, market.home_expected_goals, market.away_expected_goals)
        except ValueError:
            # One malformed CSV row (odds <= 1.0, or a totals line too lopsided
            # to invert) must not abort a whole projections run - the DC-only
            # fallback below is the honest answer for that fixture. Note the
            # Dixon-Coles RuntimeError is deliberately NOT caught anywhere:
            # that fit is one joint optimization over the entire league, so
            # non-convergence means the league model failed and must fail loud.
            blended = None
    if blended is None:
        blended = blend_fixture_goals(dc_home, dc_away, dc_home, dc_away, weight=1.0)  # no odds -> DC only

    if is_home:
        return blended.home_expected_goals, blended.away_expected_goals
    return blended.away_expected_goals, blended.home_expected_goals


def _goals_conceded_penalty(
    conn: sqlite3.Connection, season: str, position: str, expected_goals_against: float
) -> float:
    """Expected value of the -N-per-2-conceded penalty (DEF/GKP only), summed
    over goals-conceded bands via the blended Poisson distribution - not a
    single clean-sheet-vs-not binary. sum_k P(GC >= 2k) is exactly
    E[floor(GC/2)]; k is truncated at 5 because P(GC >= 12) is negligible."""
    if position not in ("DEF", "GKP"):
        return 0.0
    rate = get_rule(conn, season, f"scoring.goals_conceded.{position}", 0) or 0
    if not rate:
        return 0.0
    return sum(
        rate * goals_conceded_band_probability(expected_goals_against, min_goals=2 * k)
        for k in range(1, 6)
    )


def _historical_minutes_fraction(
    conn: sqlite3.Connection, player_id: int, market_team_id: int, season: str, as_of_date: str | None
) -> float:
    """The player's own minutes / (their team's matches x 90) over the season so
    far. This is the factor already baked into player_share_of_team_xg's
    accumulated ratio, so dividing that share by this recovers a per-90-
    equivalent share."""
    clause, extra = ("AND match_date < ?", (as_of_date,)) if as_of_date else ("", ())
    player_minutes = conn.execute(
        f"SELECT SUM(minutes) AS total FROM player_match_stats_history "
        f"WHERE player_id=? AND season=? {clause}",
        (player_id, season) + extra,
    ).fetchone()["total"] or 0
    team_matches = conn.execute(
        f"SELECT COUNT(DISTINCT understat_match_id) AS n FROM player_match_stats_history "
        f"WHERE market_team_id=? AND season=? {clause}",
        (market_team_id, season) + extra,
    ).fetchone()["n"] or 0
    if not team_matches:
        return 0.0
    return player_minutes / (team_matches * 90)


def _scoring_season(conn: sqlite3.Connection, season: str | None) -> str | None:
    """Which season's `rules` rows to price a match with. Normally the same
    season the stats come from, but a backtest replaying e.g. 2024-25 against a
    DB that only ever ingested the live season's rules would otherwise get
    `get_rule` defaults for every scoring key - i.e. goals/assists/cards all
    worth 0, silently collapsing the estimate to appearance points. When the
    requested season has no rules at all, price with the live season instead
    (FPL's core scoring values are stable across these seasons) rather than
    returning a plausible-looking zero."""
    if season is None:
        return current_season(conn)
    exists = conn.execute("SELECT 1 FROM rules WHERE season=? LIMIT 1", (season,)).fetchone()
    return season if exists else current_season(conn)


def _player_match_rates(
    conn: sqlite3.Connection, player_id: int, as_of_date: str | None = None, season: str | None = None
) -> dict:
    """`season` defaults to the LIVE season (rules' newest row). A backtest
    replaying a historical season must pass it explicitly: every query below
    filters `season = ?`, so leaving it live against a DB that also holds the
    current season's rules silently returns zero rows for the replayed season
    rather than erroring."""
    player = conn.execute(
        "SELECT p.team_id, et.singular_name_short AS position FROM players p "
        "JOIN element_types et ON et.id = p.element_type WHERE p.id=?",
        (player_id,),
    ).fetchone()
    if player is None:
        raise ValueError(f"unknown player_id: {player_id}")
    position = player["position"]

    season = season if season is not None else current_season(conn)
    rules_season = _scoring_season(conn, season)
    goals_rate = get_rule(conn, rules_season, f"scoring.goals_scored.{position}", 0) or 0
    assists_rate = get_rule(conn, rules_season, "scoring.assists", 0) or 0
    clean_sheet_pts = get_rule(conn, rules_season, f"scoring.clean_sheets.{position}", 0) or 0

    shrunk = player_shrunk_rates(conn, player_id, season, as_of_date)
    minutes_probs = minutes_bucket_probabilities(conn, player_id, season, as_of_date)

    team_market_id = get_or_create_market_team(conn, "fpl", _fpl_team_name(conn, player["team_id"]))

    if shrunk["goals"].matches_played > 0:
        # Understat match-level data exists for this player+season - primary path.
        shrunk_goals90 = shrunk["goals"].shrunk_per90
        shrunk_xa90 = shrunk["xa"].shrunk_per90
        player_share = player_share_of_team_xg(conn, player_id, team_market_id, season, as_of_date)
        minutes_fraction = _historical_minutes_fraction(conn, player_id, team_market_id, season, as_of_date)
        # Accumulated share -> per-90-equivalent share. Capped at 1.0: a player
        # cannot own more than all of their team's xG per 90, and a tiny sample
        # (one start out of ten team matches) can otherwise blow the ratio up.
        share_per90 = min(player_share / minutes_fraction, 1.0) if minutes_fraction > 0 else 0.0
        goals_source = "understat"
    else:
        # player_match_stats_history has zero rows for this player+season - a real,
        # current condition (fpl backfill-xg is broken, see CLAUDE.md). Without this
        # branch, both the player's own rate AND the shrinkage prior come from the
        # same empty table, so shrink_rate(0, 0, 0) = 0 for every single player -
        # not a conservative estimate, a complete silent loss of the goals/assists
        # component. Falls back to season_shrunk_rate() over player_season_history
        # (official FPL data, always populated by `fpl sync-history`) - same
        # empirical-Bayes machinery bonus_regression.py already established.
        # Column choice matches the primary path's own asymmetry: goals uses actual
        # goals_scored, assists uses official expected_assists (xA), same reasoning
        # Pillar 0 already applied when both came from Understat.
        # season_shrunk_rate's before_season is player_season_history's own
        # "YYYY/YY" convention, not rules.season's "YYYY-YY" - see
        # player_regression.py's module docstring. Converting `season` (e.g.
        # "2024-25" -> "2024/25") and passing it as a strict upper bound keeps a
        # walk-forward backtest of a historical season leakage-free the same way
        # every other query in this function already is: without this, a
        # backtest replaying 2024-25 with Understat data unavailable would fall
        # back to the MOST RECENT season_history row available - which could be
        # a later, real season - leaking future data into an "as of" estimate.
        # In live mode `season` is the current (in-progress or not-yet-started)
        # season, which has no player_season_history rows yet either way, so
        # this is a no-op there and changes nothing about live behavior.
        before_season = season.replace("-", "/") if season else None
        shrunk_goals90 = season_shrunk_rate(conn, player_id, "goals_scored", before_season).shrunk_per90
        shrunk_xa90 = season_shrunk_rate(conn, player_id, "expected_assists", before_season).shrunk_per90
        goals_source = "season_fallback"

        # season_shrunk_rate falls through to a pure positional average when
        # player_season_history is also empty (a player genuinely new to the
        # English top flight this season - no PL history to shrink at all).
        # Before accepting that positional-average guess, check whether this
        # is a real transfer-window signing with a real cross-league record
        # (models/squad_churn.py's sibling, ingestion/cross_league_source.py -
        # see docs/superpowers/specs/2026-08-20-preseason-calibration-design.md).
        # Both rates are taken from the same cross-league row together, not
        # mixed component-by-component with the positional-average fallback -
        # a real signal about this specific player beats a population guess.
        cross_league = get_cross_league_prior(conn, player_id)
        if cross_league is not None:
            shrunk_goals90 = cross_league["goals_per90"]
            shrunk_xa90 = cross_league["xa_per90"]
            goals_source = "cross_league"

        # Cards has no season-grain fallback via season_shrunk_rate: FPL's own
        # season-totals endpoint (player_season_history, history_past) carries
        # no cards field at all - a real source limitation, not an oversight
        # (confirmed against the schema). Without this, cards silently falls
        # all the way to the pure positional average for every player whenever
        # current-season Understat is empty - which is every player right now,
        # preseason. The closest real personal signal available is the
        # player's own PRIOR season's Understat match-level discipline rate
        # (richer than a season total anyway - real per-match minutes/cards,
        # not FPL's aggregate). Using an entirely earlier season's full data
        # (as_of_date=None) is leakage-free for a walk-forward backtest of
        # `season` by construction, same reasoning season_shrunk_rate's own
        # before_season already relies on. Falls through to shrink_rate's own
        # zero-matches behavior (pure positional average) if the player has
        # no Understat rows last season either - never fabricated.
        prior_season_str = prior_season(season) if season else None
        if prior_season_str:
            prior_cards = player_shrunk_rates(conn, player_id, prior_season_str, as_of_date=None)["cards"]
            if prior_cards.matches_played > 0:
                shrunk["cards"] = prior_cards

        player_share = 0.0
        minutes_fraction = 0.0
        # No shot-level data to derive a real team-xG share from, so this
        # approximates it: the player's own shrunk per-90 goal rate against a
        # league-average team goals rate, rather than this specific team's rate
        # (team-level goal aggregation isn't available without Understat either).
        # A real, documented simplification, not a fabricated precise share -
        # still lets the existing team_goals * share_per90 formula respond to
        # fixture difficulty via team_goals, just with a coarser baseline.
        share_per90 = min(shrunk_goals90 / _LEAGUE_AVERAGE_GOALS, 1.0)

    bonus90 = expected_bonus_per90(conn, player_id).shrunk_per90

    # Defensive contribution ("DefCon") - a real FPL scoring rule (10 CBIT for
    # DEF, 12 CBIRT for MID/FWD, 2 points, capped) completely unmodeled before
    # 2026-08-20 despite player_season_history already carrying the raw action
    # count. Always season-grain, same reason bonus is (no source this project
    # has carries match-level CBIT/CBIRT counts) - see
    # models/defensive_contribution.py's module docstring.
    defcon_actions90 = expected_defcon_actions_per90(conn, player_id).shrunk_per90
    defcon_pts_rule = get_rule(conn, rules_season, f"scoring.defensive_contribution.{position}", 0) or 0

    yellow_card_rate = get_rule(conn, rules_season, "scoring.yellow_cards", -1) or -1

    return {
        "position": position, "team_id": player["team_id"],
        "goals_rate": goals_rate, "assists_rate": assists_rate, "clean_sheet_pts": clean_sheet_pts,
        "shrunk_goals90": shrunk_goals90,
        "shrunk_xa90": shrunk_xa90, "shrunk_cards90": shrunk["cards"].shrunk_per90,
        "yellow_card_rate": yellow_card_rate,
        "player_share": player_share, "player_share_per90": share_per90,
        "historical_minutes_fraction": minutes_fraction,
        "bonus90": bonus90, "minutes_probs": minutes_probs,
        "defcon_actions90": defcon_actions90, "defcon_pts_rule": defcon_pts_rule,
        "season": season, "rules_season": rules_season, "goals_source": goals_source,
    }


def _match_components(
    conn: sqlite3.Connection, rates: dict, team_goals: float, opp_goals: float, damping: float = 1.0
) -> float:
    """One fixture's expected points for a player. `damping` is the flat
    rotation-risk discount applied per extra match in a multi-fixture window."""
    probs = rates["minutes_probs"]
    effective_minutes_fraction = (probs.p_partial / 3 + probs.p_full) * damping

    appearance = expected_appearance_points(probs) * damping
    # player_share_per90 (not the accumulated player_share) - see module docstring.
    goals = team_goals * rates["player_share_per90"] * effective_minutes_fraction * rates["goals_rate"]
    assists = rates["shrunk_xa90"] * rates["assists_rate"] * effective_minutes_fraction
    bonus = rates["bonus90"] * effective_minutes_fraction
    cards = rates["shrunk_cards90"] * rates["yellow_card_rate"] * effective_minutes_fraction

    # A clean sheet is a hard 60-minute threshold, not something a partial
    # appearance earns a fraction of, so it uses p_full rather than the blended
    # minutes fraction. The goals-conceded penalty genuinely does scale with
    # time on the pitch, so that one keeps the blended fraction.
    p_sixty_plus = min(probs.p_full * damping, 1.0)
    clean_sheet = clean_sheet_probability(opp_goals) * rates["clean_sheet_pts"] * p_sixty_plus
    conceded = _goals_conceded_penalty(conn, rates["rules_season"], rates["position"], opp_goals) * min(
        effective_minutes_fraction, 1.0
    )
    # Same p_full-based weight as clean_sheet, not the blended partial fraction -
    # a threshold stat (10-12 actions in one match) needs a full match to
    # plausibly reach, same reasoning already established there.
    defcon = defcon_points_probability(rates["defcon_actions90"], rates["position"]) * rates["defcon_pts_rule"] * p_sixty_plus

    return appearance + goals + assists + bonus + clean_sheet + cards + conceded + defcon


def _fixture_date(fixture_row) -> str:
    """Plain YYYY-MM-DD. Truncating the kickoff timestamp matters: match_date in
    match_results_history is date-only, and '2026-08-21' < '2026-08-21T19:00Z'
    compares True as a string, so an untruncated cutoff would let a match played
    the same day leak into its own prediction."""
    return (fixture_row["kickoff_time"] or "2099-01-01")[:10]


def _fixture_goals_for(conn: sqlite3.Connection, fixture_row, team_id: int) -> tuple[float, float]:
    opponent_id = fixture_row["team_a"] if fixture_row["team_h"] == team_id else fixture_row["team_h"]
    return _blended_fixture_goals(conn, fixture_row["id"], team_id, opponent_id, _fixture_date(fixture_row))


_FLOOR_CEILING_TRIALS = 500
_FLOOR_PERCENTILE = 10
_CEILING_PERCENTILE = 90


def _sampled_floor_ceiling(
    conn: sqlite3.Connection, rates: dict, fixtures_with_goals: list[tuple], median: float,
    effective_minutes_fraction: float, ceiling_matches: int,
) -> tuple[float, float]:
    """Real P10/P90 from the same Monte-Carlo per-trial point model
    scenario_engine.py already uses for season-long simulation (Poisson-
    correlated Dixon-Coles scorelines, per-trial minutes-bucket/goals/
    assists/cards/bonus draws) - replaces the old flat multiplicative
    heuristic (median*0.5 floor, median*1.8+goal-upside ceiling), which this
    project's own CLAUDE.md had disclosed as "not fit to real tail-outcome
    data" since Pillar 1 Plan 1b. Falls back to that same heuristic only when
    there's no real fixture to sample from (a genuine blank gameweek) -
    fabricating a Dixon-Coles rho with no fixture to fit it from would be
    less honest than the disclosed heuristic it replaces.

    Home/away orientation matters here and is easy to get backwards:
    `_fixture_goals_for` returns (team, opponent) goals, but
    sample_fixture_scorelines' Dixon-Coles tau correlation is asymmetric
    between the true home/away sides, not team/opponent - re-orients to
    (home, away) before sampling and back to (team, opponent) after, exactly
    like scenario_engine.py's own `_draw_fixture_for_team` does, rather than
    naively feeding team/opponent goals in as if they were home/away. Takes
    (fixture_row, (team_goals, opp_goals)) pairs - the caller's own already-
    computed goals_pairs, reused rather than calling _fixture_goals_for again
    (each call can trigger a real Dixon-Coles refit on a cache miss, and this
    function is called once per player per squad build - a second redundant
    call site here was a real, measured perf regression, caught before
    shipping this)."""
    if not fixtures_with_goals:
        floor = round(median * 0.5, 2)
        ceiling = round(median * 1.8 + _CEILING_GOAL_UPSIDE * effective_minutes_fraction * ceiling_matches, 2)
        return floor, ceiling

    conceded_rate = get_rule(conn, rates["rules_season"], f"scoring.goals_conceded.{rates['position']}", 0) or 0
    if rates["position"] not in ("DEF", "GKP"):
        conceded_rate = 0

    rng = np.random.default_rng()
    total = np.zeros(_FLOOR_CEILING_TRIALS)
    for f, (team_goals, opp_goals) in fixtures_with_goals:
        is_home = f["team_h"] == rates["team_id"]
        lam, mu = (team_goals, opp_goals) if is_home else (opp_goals, team_goals)

        dc_model = _get_or_fit_dc_model(conn, _fixture_date(f))
        rho = dc_model.rho if dc_model is not None else 0.0

        home_goals, away_goals = sample_fixture_scorelines(rng, lam, mu, rho, _FLOOR_CEILING_TRIALS)
        trial_team_goals, trial_opp_goals = (home_goals, away_goals) if is_home else (away_goals, home_goals)
        total = total + sample_player_trial_points(rng, rates, conceded_rate, trial_team_goals, trial_opp_goals)

    floor = round(float(np.percentile(total, _FLOOR_PERCENTILE)), 2)
    ceiling = round(float(np.percentile(total, _CEILING_PERCENTILE)), 2)
    return floor, ceiling


@dataclass(frozen=True)
class ExpectedPoints:
    player_id: int
    position: str
    floor: float
    median: float
    ceiling: float
    confidence: str
    expected_minutes: float
    model_version: str


def expected_points(
    conn: sqlite3.Connection, player_id: int, n_gw: int = 1, from_event: int | None = None
) -> ExpectedPoints:
    """Single-match expected points, with the fixture-level goals inputs averaged
    over `n_gw` unfinished fixtures (v1's `n_gw` semantics - a window of context,
    not a multi-match total). Use expected_points_window() for a genuine
    cumulative total across a window.

    `from_event` optionally targets a SPECIFIC future gameweek's fixture(s)
    instead of the default "next n_gw unfinished fixtures from right now" -
    lets a caller evaluate a candidate GAMEWEEK rather than always "today".
    Added for chip-window scheduling (optimization/chips.py) and captaincy
    evaluation (optimization/captaincy.py), both of which used to always
    evaluate "today's" squad/captain and assume it for every event under
    comparison - see CLAUDE.md's "chip selection is event-invariant"
    limitation, closed by this. Existing callers that don't pass it get the
    exact same code path as before (the `else` branch below is byte-for-byte
    unchanged), zero behavior change for them."""
    rates = _player_match_rates(conn, player_id)
    em = expected_minutes(conn, player_id)
    probs = rates["minutes_probs"]
    effective_minutes_fraction = probs.p_partial / 3 + probs.p_full

    upcoming = conn.execute(
        "SELECT id, team_h, team_a, kickoff_time, event FROM fixtures "
        "WHERE (team_h=? OR team_a=?) AND finished=0 ORDER BY event",
        (rates["team_id"], rates["team_id"]),
    ).fetchall()
    if from_event is not None:
        fixtures = [
            f for f in upcoming
            if f["event"] is not None and from_event <= f["event"] < from_event + max(n_gw, 1)
        ]
    else:
        # Window by gameweek, not by row count, so a double gameweek contributes
        # both of its fixtures to the average rather than eating the whole n_gw budget.
        first_event = next((f["event"] for f in upcoming if f["event"] is not None), None)
        fixtures = [
            f for f in upcoming
            if first_event is None or f["event"] is None or f["event"] < first_event + max(n_gw, 1)
        ]

    if fixtures:
        goals_pairs = [_fixture_goals_for(conn, f, rates["team_id"]) for f in fixtures]
    else:
        goals_pairs = [(_LEAGUE_AVERAGE_GOALS, _LEAGUE_AVERAGE_GOALS)]

    if from_event is not None and len(goals_pairs) > 1:
        # from_event always targets exactly one specific gameweek in every real
        # caller (captaincy.py/chips.py's per-candidate-GW evaluation, always
        # n_gw=1) - a double gameweek's two fixtures must SUM into that
        # gameweek's real total (real FPL scoring sums both matches' points
        # before any captain multiplier applies), not collapse into one
        # averaged match-equivalent snapshot. The averaging path below is
        # correct and untouched for the from_event=None "next n_gw fixtures
        # from now" rolling context-window case (squad-building/wildcard-value
        # callers), which is deliberately a smoothed single-match-equivalent
        # signal, not a specific gameweek's total - see the module docstring.
        # len(goals_pairs)==1 (the overwhelming common case, and the blank-
        # gameweek league-average fallback) always falls through to the
        # average branch below, which is identical to summing for one item -
        # zero behavior change for every non-double-gameweek caller.
        median = sum(_match_components(conn, rates, tg, og) for tg, og in goals_pairs)
        ceiling_matches = len(goals_pairs)
    else:
        team_goals = sum(g[0] for g in goals_pairs) / len(goals_pairs)
        opp_goals = sum(g[1] for g in goals_pairs) / len(goals_pairs)
        median = _match_components(conn, rates, team_goals, opp_goals)
        ceiling_matches = 1

    floor, ceiling = _sampled_floor_ceiling(
        conn, rates, list(zip(fixtures, goals_pairs)), median, effective_minutes_fraction, ceiling_matches,
    )

    return ExpectedPoints(
        player_id=player_id, position=rates["position"], floor=floor, median=round(median, 2),
        ceiling=ceiling, confidence=em.confidence, expected_minutes=em.expected_minutes,
        model_version=MODEL_VERSION,
    )


@dataclass(frozen=True)
class WindowExpectedPoints:
    player_id: int
    n_gw: int
    fixture_count: int
    total_median: float
    model_version: str


def expected_points_window(
    conn: sqlite3.Connection, player_id: int, n_gw: int, from_event: int | None = None
) -> WindowExpectedPoints:
    """Cumulative EV across a window - correctly sums doubles, correctly zeroes blanks."""
    rates = _player_match_rates(conn, player_id)
    start = from_event if from_event is not None else _reference_event(conn)
    fixtures = conn.execute(
        "SELECT id, team_h, team_a, kickoff_time FROM fixtures "
        "WHERE (team_h=? OR team_a=?) AND event >= ? AND event < ? ORDER BY event",
        (rates["team_id"], rates["team_id"], start, start + n_gw),
    ).fetchall()

    total = 0.0
    for i, fixture in enumerate(fixtures):
        team_goals, opp_goals = _fixture_goals_for(conn, fixture, rates["team_id"])
        total += _match_components(
            conn, rates, team_goals, opp_goals, damping=_ROTATION_DAMPING_PER_EXTRA_MATCH ** i
        )

    return WindowExpectedPoints(
        player_id=player_id, n_gw=n_gw, fixture_count=len(fixtures),
        total_median=round(total, 2), model_version=MODEL_VERSION,
    )


@dataclass(frozen=True)
class CoreExpectedPoints:
    player_id: int
    position: str
    appearance: float
    goals: float
    assists: float
    cards: float
    total: float
    model_version: str
    season: str | None
    minutes_source: str


def core_expected_points(
    conn: sqlite3.Connection, player_id: int, as_of_date: str | None = None, season: str | None = None
) -> CoreExpectedPoints:
    """Team-blend-free "core" per-match points - appearance + goals + assists +
    cards - for one player, as of `as_of_date` (None = live, all data) within
    `season` (None = the live season from the `rules` table).

    This is the entry point the walk-forward backtest harness scores against.
    expected_points()'s public signature is locked to (conn, player_id, n_gw),
    so `as_of_date` cannot be threaded through it; this function exists so an
    as-of-a-past-date path is reachable from outside the module without a
    caller having to reimplement the player layer.

    PASS `season` WHEN BACKTESTING. Every underlying query filters
    `season = ?`; defaulting to the live season against a real DB (which holds
    the current season's rules) would match zero rows for a replayed historical
    season - all-zero shrunk rates and a fallback minutes prior - producing a
    plausible-looking but meaningless number rather than an error.

    LEAKAGE, precisely:
    - The goals/assists/cards rates and the EMPIRICAL minutes-bucket path are
      leakage-free: every query is bounded to strictly before `as_of_date`.
    - The FALLBACK minutes path is NOT. When a player has fewer than
      _MIN_MATCHES_FOR_EMPIRICAL pre-cutoff Understat matches,
      minutes_bucket_probabilities() falls through to expected_minutes(),
      which is a LIVE-prediction function built before backtesting existed: it
      reads current `players.status`, the newest `player_stats_snapshot` row,
      and a live count of finished events, none of them date-scoped. In a
      walk-forward backtest that means early-season rounds and low-minutes
      players can leak end-of-season information into an "as of" estimate.
      `minutes_source` on the result says which path ran ("empirical" vs
      "fallback_prior") so the caller can exclude or discount those rows
      rather than silently trusting them. Making expected_minutes() itself
      date-aware was ruled out of scope - it is a pre-existing live module and
      changing it would move the live prediction path too.

    Deliberately excluded, matching what the harness can actually reconstruct
    from historical rows: bonus (Understat carries no BPS), clean sheets and
    the goals-conceded penalty (both need the opponent's blended goals
    distribution for that specific historical fixture). The goals term here
    uses the shrunk per-90 goal rate directly rather than the team-goals x
    xG-share route the live model takes, for the same reason."""
    rates = _player_match_rates(conn, player_id, as_of_date, season)
    probs = rates["minutes_probs"]
    effective_minutes_fraction = probs.p_partial / 3 + probs.p_full

    appearance = expected_appearance_points(probs)
    goals = rates["shrunk_goals90"] * effective_minutes_fraction * rates["goals_rate"]
    assists = rates["shrunk_xa90"] * effective_minutes_fraction * rates["assists_rate"]
    cards = rates["shrunk_cards90"] * effective_minutes_fraction * rates["yellow_card_rate"]

    return CoreExpectedPoints(
        player_id=player_id, position=rates["position"],
        appearance=round(appearance, 4), goals=round(goals, 4),
        assists=round(assists, 4), cards=round(cards, 4),
        total=round(appearance + goals + assists + cards, 4),
        model_version=MODEL_VERSION,
        season=rates["season"], minutes_source=probs.source,
    )
