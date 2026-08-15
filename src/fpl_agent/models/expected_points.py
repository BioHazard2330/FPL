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
- Clean-sheet and goals-conceded-band probabilities: read directly off the
  blended Poisson distribution, not a linear heuristic on fixture difficulty.
- Bonus: still last-season per-90 prior (models/player_regression.py's shot
  data has no bonus/BPS field - Understat doesn't carry it - so this
  component is honestly NOT part of the calibration work here; a real BPS
  regression needs current-season player_stats_snapshot history, which only
  exists once games are actually played this season).
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

Two interface notes, both deliberate:

- expected_points()'s `n_gw` argument is kept for backwards compatibility
  (optimization/squad.py, optimization/chips.py, models/differentials.py,
  models/breakouts.py and the CLI all pass it) but is no longer read. v1
  used it only to average fixture difficulty across a window while still
  returning a single-match estimate; v2 reads the actual next fixture
  instead, so there is nothing left for it to select. Use
  expected_points_window() for genuine multi-gameweek totals.
- Every number here is still a per-match estimate. Nothing in this module
  multiplies by fixture count except expected_points_window().
"""

import sqlite3
from dataclasses import dataclass

from fpl_agent.ingestion.market_identity import get_or_create_market_team
from fpl_agent.models.blend import (
    blend_fixture_goals,
    clean_sheet_probability,
    goals_conceded_band_probability,
    market_implied_fixture_goals,
)
from fpl_agent.models.expected_minutes import expected_minutes
from fpl_agent.models.fixtures import _reference_event
from fpl_agent.models.minutes_distribution import (
    expected_appearance_points,
    minutes_bucket_probabilities,
)
from fpl_agent.models.odds_devig import devig_match_odds, devig_totals_odds
from fpl_agent.models.player_regression import player_share_of_team_xg, player_shrunk_rates
from fpl_agent.models.rules import current_season, get_rule
from fpl_agent.models.team_strength_dc import expected_goals as dc_expected_goals
from fpl_agent.models.team_strength_dc import fit_dixon_coles, load_matches_for_fitting

MODEL_VERSION = "calibrated-v2"

_CEILING_GOAL_UPSIDE = 4.0
_ROTATION_DAMPING_PER_EXTRA_MATCH = 0.9
_LEAGUE_AVERAGE_GOALS = 1.3  # used when there isn't enough history to fit Dixon-Coles yet
_MIN_MATCHES_TO_FIT_DC = 10

# Keyed by (id(conn), as_of_date); the connection itself is stored alongside the
# model so its id() can't be recycled into a false cache hit after it's closed.
_dc_model_cache: dict[tuple[int, str], tuple[sqlite3.Connection, object]] = {}


def _fpl_team_name(conn: sqlite3.Connection, team_id: int) -> str:
    return conn.execute("SELECT name FROM teams WHERE id=?", (team_id,)).fetchone()["name"]


def _get_or_fit_dc_model(conn: sqlite3.Connection, as_of_date: str):
    """Cached per (connection, as_of_date) - refitting Dixon-Coles (a numerical
    optimization over every team) on every single player lookup would be
    needlessly slow; callers within the same backtest round or the same live
    prediction pass share one fit. The cache is not invalidated by new match
    ingestion, so a long-lived process that syncs mid-run would keep the older
    fit for an already-seen as_of_date."""
    key = (id(conn), as_of_date)
    cached = _dc_model_cache.get(key)
    if cached is not None:
        return cached[1]

    matches, team_ids = load_matches_for_fitting(conn, as_of_date)
    if len(matches) < _MIN_MATCHES_TO_FIT_DC or len(team_ids) < 2:
        model = None
    else:
        model = fit_dixon_coles(matches, team_ids)
    _dc_model_cache[key] = (conn, model)
    return model


def _blended_fixture_goals(
    conn: sqlite3.Connection, fixture_id: int, team_id: int, opponent_team_id: int, as_of_date: str
) -> tuple[float, float]:
    """(team expected goals, opponent expected goals) for one fixture."""
    home_row = conn.execute("SELECT team_h, team_a FROM fixtures WHERE id=?", (fixture_id,)).fetchone()
    is_home = home_row is not None and home_row["team_h"] == team_id

    team_market_id = get_or_create_market_team(conn, "fpl", _fpl_team_name(conn, team_id))
    opp_market_id = get_or_create_market_team(conn, "fpl", _fpl_team_name(conn, opponent_team_id))

    dc_model = _get_or_fit_dc_model(conn, as_of_date)
    if dc_model is not None and team_market_id in dc_model.teams and opp_market_id in dc_model.teams:
        home_id, away_id = (team_market_id, opp_market_id) if is_home else (opp_market_id, team_market_id)
        dc_home, dc_away = dc_expected_goals(dc_model, home_id, away_id)
    else:
        dc_home = dc_away = _LEAGUE_AVERAGE_GOALS

    ordered = (team_market_id, opp_market_id) if is_home else (opp_market_id, team_market_id)
    match_row = conn.execute(
        "SELECT id FROM match_results_history WHERE (home_team_id=? AND away_team_id=?) "
        "AND match_date < ? ORDER BY match_date DESC LIMIT 1",
        ordered + (as_of_date,),
    ).fetchone()
    odds_row = None
    if match_row:
        odds_row = conn.execute(
            "SELECT * FROM team_match_odds_history WHERE match_id=? ORDER BY retrieved_at DESC LIMIT 1",
            (match_row["id"],),
        ).fetchone()

    # Every odds column is nullable in the schema, so require the full 1X2 +
    # over/under set before devigging rather than trusting the ingester's
    # current guarantee that 1X2 is always populated.
    _odds_keys = ("home_win_odds", "draw_odds", "away_win_odds", "over_2_5_odds", "under_2_5_odds")
    if odds_row is not None and all(odds_row[k] for k in _odds_keys):
        outcome = devig_match_odds(odds_row["home_win_odds"], odds_row["draw_odds"], odds_row["away_win_odds"])
        totals = devig_totals_odds(odds_row["over_2_5_odds"], odds_row["under_2_5_odds"])
        market = market_implied_fixture_goals(outcome, totals)
        blended = blend_fixture_goals(dc_home, dc_away, market.home_expected_goals, market.away_expected_goals)
    else:
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


def _player_match_rates(conn: sqlite3.Connection, player_id: int, as_of_date: str | None = None) -> dict:
    player = conn.execute(
        "SELECT p.team_id, et.singular_name_short AS position FROM players p "
        "JOIN element_types et ON et.id = p.element_type WHERE p.id=?",
        (player_id,),
    ).fetchone()
    if player is None:
        raise ValueError(f"unknown player_id: {player_id}")
    position = player["position"]

    season = current_season(conn)
    goals_rate = get_rule(conn, season, f"scoring.goals_scored.{position}", 0) or 0
    assists_rate = get_rule(conn, season, "scoring.assists", 0) or 0
    clean_sheet_pts = get_rule(conn, season, f"scoring.clean_sheets.{position}", 0) or 0

    shrunk = player_shrunk_rates(conn, player_id, season, as_of_date)
    minutes_probs = minutes_bucket_probabilities(conn, player_id, season, as_of_date)

    team_market_id = get_or_create_market_team(conn, "fpl", _fpl_team_name(conn, player["team_id"]))
    player_share = player_share_of_team_xg(conn, player_id, team_market_id, season, as_of_date)

    prior = conn.execute(
        "SELECT bonus, minutes FROM player_season_history WHERE player_id=? ORDER BY season_name DESC LIMIT 1",
        (player_id,),
    ).fetchone()
    bonus90 = (prior["bonus"] / prior["minutes"] * 90) if prior and prior["minutes"] else 0.0

    yellow_card_rate = get_rule(conn, season, "scoring.yellow_cards", -1) or -1

    return {
        "position": position, "team_id": player["team_id"],
        "goals_rate": goals_rate, "assists_rate": assists_rate, "clean_sheet_pts": clean_sheet_pts,
        "shrunk_xa90": shrunk["xa"].shrunk_per90, "shrunk_cards90": shrunk["cards"].shrunk_per90,
        "yellow_card_rate": yellow_card_rate, "player_share": player_share,
        "bonus90": bonus90, "minutes_probs": minutes_probs, "season": season,
    }


def _match_components(
    conn: sqlite3.Connection, rates: dict, team_goals: float, opp_goals: float, damping: float = 1.0
) -> float:
    """One fixture's expected points for a player. `damping` is the flat
    rotation-risk discount applied per extra match in a multi-fixture window."""
    probs = rates["minutes_probs"]
    effective_minutes_fraction = (probs.p_partial / 3 + probs.p_full) * damping

    appearance = expected_appearance_points(probs) * damping
    goals = team_goals * rates["player_share"] * effective_minutes_fraction * rates["goals_rate"]
    assists = rates["shrunk_xa90"] * rates["assists_rate"] * effective_minutes_fraction
    bonus = rates["bonus90"] * effective_minutes_fraction
    cards = rates["shrunk_cards90"] * rates["yellow_card_rate"] * effective_minutes_fraction

    played = min(effective_minutes_fraction, 1.0)
    clean_sheet = clean_sheet_probability(opp_goals) * rates["clean_sheet_pts"] * played
    conceded = _goals_conceded_penalty(conn, rates["season"], rates["position"], opp_goals) * played

    return appearance + goals + assists + bonus + clean_sheet + cards + conceded


def _fixture_goals_for(conn: sqlite3.Connection, fixture_row, team_id: int) -> tuple[float, float]:
    opponent_id = fixture_row["team_a"] if fixture_row["team_h"] == team_id else fixture_row["team_h"]
    as_of = fixture_row["kickoff_time"] or "2099-01-01"
    return _blended_fixture_goals(conn, fixture_row["id"], team_id, opponent_id, as_of)


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


def expected_points(conn: sqlite3.Connection, player_id: int, n_gw: int = 1) -> ExpectedPoints:
    """Single-match expected points for the player's next unfinished fixture.
    `n_gw` is accepted for backwards compatibility and unused - see module
    docstring."""
    rates = _player_match_rates(conn, player_id)
    em = expected_minutes(conn, player_id)
    probs = rates["minutes_probs"]
    effective_minutes_fraction = probs.p_partial / 3 + probs.p_full

    fixture = conn.execute(
        "SELECT id, team_h, team_a, kickoff_time FROM fixtures WHERE (team_h=? OR team_a=?) AND finished=0 "
        "ORDER BY event LIMIT 1",
        (rates["team_id"], rates["team_id"]),
    ).fetchone()

    if fixture:
        team_goals, opp_goals = _fixture_goals_for(conn, fixture, rates["team_id"])
    else:
        team_goals = opp_goals = _LEAGUE_AVERAGE_GOALS

    median = _match_components(conn, rates, team_goals, opp_goals)
    floor = round(median * 0.5, 2)
    ceiling = round(median * 1.8 + _CEILING_GOAL_UPSIDE * effective_minutes_fraction, 2)

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
