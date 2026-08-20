import pytest

from fpl_agent.ingestion.market_identity import get_or_create_market_team
from fpl_agent.ingestion.sync import (
    _upsert_many,
    _extract_season,
    sync_rules,
    sync_stats_snapshot,
)
from fpl_agent.models.expected_points import (
    MODEL_VERSION,
    _blended_fixture_goals,
    _player_match_rates,
    core_expected_points,
    expected_points,
)
from fpl_agent.models.rules import current_season
from fpl_agent.normalization.fpl_core import (
    flatten_rules,
    normalize_element_types,
    normalize_events,
    normalize_player_stats,
    normalize_players,
    normalize_teams,
)

from test_expected_minutes import _insert_season_history
from test_sync import make_bootstrap


def _seed_full(conn, bootstrap, now):
    _upsert_many(conn, "teams", normalize_teams(bootstrap), now)
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), now)
    _upsert_many(conn, "events", normalize_events(bootstrap), now)
    _upsert_many(conn, "players", normalize_players(bootstrap), now)
    sync_stats_snapshot(conn, normalize_player_stats(bootstrap), now)
    season = _extract_season(bootstrap)
    sync_rules(conn, flatten_rules(bootstrap), season, "fpl_api_bootstrap", now)
    conn.commit()


def test_expected_points_shape_and_bounds(db_conn):
    bootstrap = make_bootstrap()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420, expected_goals=0.0, expected_assists=0.0, bonus=11)

    ep = expected_points(db_conn, 1)

    assert ep.model_version == MODEL_VERSION
    assert ep.floor <= ep.median <= ep.ceiling
    assert ep.floor >= 0
    assert ep.median > 0  # appearance points alone, since FIT with a minutes prior


def test_expected_points_zero_for_confirmed_unavailable(db_conn):
    bootstrap = make_bootstrap()
    bootstrap["elements"][0]["status"] = "u"
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420)

    ep = expected_points(db_conn, 1)

    assert ep.median == 0.0
    assert ep.floor == 0.0


def test_model_version_is_calibrated_v2():
    assert MODEL_VERSION == "calibrated-v2"


def test_expected_points_falls_back_gracefully_with_no_market_data(db_conn):
    # No match_results_history/player_match_stats_history/odds rows at all -
    # must not crash, must return a sane zero/near-zero-confidence estimate
    # rather than fabricating a market blend from nothing.
    bootstrap = make_bootstrap()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420)

    result = expected_points(db_conn, 1)

    assert result.median >= 0
    assert result.model_version == "calibrated-v2"
    # Degraded, not fabricated: no shot-level data -> no xG share, so the
    # goals term contributes nothing and the estimate is appearance+bonus only.
    from fpl_agent.models.player_regression import player_share_of_team_xg

    market_team_id = get_or_create_market_team(db_conn, "fpl", "Arsenal")
    season = current_season(db_conn)
    assert player_share_of_team_xg(db_conn, 1, market_team_id, season) == 0.0


def _bootstrap_two_teams_full_scoring():
    bootstrap = make_bootstrap()
    bootstrap["teams"].append({
        "id": 2, "code": 8, "name": "Chelsea", "short_name": "CHE",
        "strength_overall_home": 4, "strength_overall_away": 4,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    bootstrap["game_config"]["scoring"].update({
        "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
        "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
        "yellow_cards": -1,
    })
    return bootstrap


_FIXTURE_DATE = "2026-08-21"


def _seed_market_history(conn, season, home_market_id, away_market_id, odds_match_date=_FIXTURE_DATE, odds=None):
    # 12 matches: enough for _get_or_fit_dc_model's >=10 threshold to fit rather
    # than fall back to the 1.3 league average.
    for i in range(12):
        h, a = (home_market_id, away_market_id) if i % 2 == 0 else (away_market_id, home_market_id)
        conn.execute(
            "INSERT INTO match_results_history (season, match_date, home_team_id, away_team_id, "
            "home_goals, away_goals, source, retrieved_at) VALUES (?,?,?,?,?,?,'test','t0')",
            (season, f"2026-0{1 + i % 5}-{10 + i:02d}", h, a, 3, 0),
        )
    cur = conn.execute(
        "INSERT INTO match_results_history (season, match_date, home_team_id, away_team_id, "
        "home_goals, away_goals, source, retrieved_at) VALUES (?,?,?,?,2,0,'test','t0')",
        (season, odds_match_date, home_market_id, away_market_id),
    )
    conn.execute(
        "INSERT INTO team_match_odds_history (match_id, source, bookmaker, home_win_odds, draw_odds, "
        "away_win_odds, over_2_5_odds, under_2_5_odds, retrieved_at) VALUES (?,'test','avg',?,?,?,?,?,'t0')",
        (cur.lastrowid,) + (odds or (1.4, 5.0, 8.0, 1.7, 2.1)),
    )
    conn.commit()


def _insert_fixture(conn, fixture_id, event, team_h, team_a, date=_FIXTURE_DATE):
    conn.execute(
        "INSERT INTO fixtures (id,code,event,kickoff_time,team_h,team_a,team_h_score,team_a_score,"
        "team_h_difficulty,team_a_difficulty,finished,started,updated_at) "
        "VALUES (?,?,?,?,?,?,NULL,NULL,3,3,0,0,'t0')",
        (fixture_id, fixture_id, event, f"{date}T19:00:00Z", team_h, team_a),
    )
    conn.commit()


def _insert_match_stat(conn, season, match_id, player_id, market_team_id, date, minutes=90, xg=0.6, goals=1):
    conn.execute(
        "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, "
        "market_team_id, season, match_date, minutes, goals, assists, shots, xg, xa, key_passes, "
        "yellow_cards, red_cards, retrieved_at) VALUES (?,?,?,?,?,?,?,?,1,4,?,0.3,2,1,0,'t0')",
        (match_id, f"u{player_id}", player_id, market_team_id, season, date, minutes, goals, xg),
    )
    conn.commit()


def _seed_player_match_stats(conn, season, player_id, market_team_id):
    for i in range(6):
        _insert_match_stat(conn, season, f"m{i}", player_id, market_team_id, f"2026-05-{10 + i:02d}")


def _seed_two_team_world(db_conn, odds_match_date=_FIXTURE_DATE, odds=None, with_player_stats=True):
    bootstrap = _bootstrap_two_teams_full_scoring()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420, bonus=25)
    _insert_fixture(db_conn, 1, 1, 1, 2)

    season = current_season(db_conn)
    arsenal = get_or_create_market_team(db_conn, "fpl", "Arsenal")
    chelsea = get_or_create_market_team(db_conn, "fpl", "Chelsea")
    _seed_market_history(db_conn, season, arsenal, chelsea, odds_match_date, odds)
    if with_player_stats:
        _seed_player_match_stats(db_conn, season, 1, arsenal)
    return season, arsenal, chelsea


def _goals_without_odds(db_conn):
    """Recompute the same fixture after deleting every odds row. The Dixon-Coles
    fit is cached per (connection, date) and its input matches are untouched, so
    any difference is attributable to the odds path alone."""
    db_conn.execute("DELETE FROM team_match_odds_history")
    db_conn.commit()
    return _blended_fixture_goals(db_conn, 1, 1, 2, _FIXTURE_DATE)


def test_expected_points_uses_blended_market_and_model_when_data_exists(db_conn):
    season, arsenal, _ = _seed_two_team_world(db_conn)

    team_goals, opp_goals = _blended_fixture_goals(db_conn, 1, 1, 2, _FIXTURE_DATE)

    # Proves the Dixon-Coles fit + devigged-odds blend actually ran: neither side
    # is the 1.3 league-average fallback, the heavy home favourite in both the
    # results history and the odds shows up as team_goals >> opp_goals, and
    # removing the odds row visibly moves the answer (so the odds were really
    # blended in, not merely present).
    assert team_goals != 1.3 and opp_goals != 1.3
    assert team_goals > opp_goals
    assert (team_goals, opp_goals) != _goals_without_odds(db_conn)

    ep = expected_points(db_conn, 1)

    assert ep.model_version == MODEL_VERSION
    assert ep.floor <= ep.median <= ep.ceiling
    assert ep.median > 0
    # Shot-level data exists now, so the player's xG share is real, not the
    # zero-fallback the no-market-data test asserts.
    from fpl_agent.models.player_regression import player_share_of_team_xg

    assert player_share_of_team_xg(db_conn, 1, arsenal, season) > 0


def test_odds_from_a_different_match_are_never_blended_in(db_conn):
    # Regression: the lookup used to be "most recent prior meeting between these
    # two teams", unbounded in age, so an unplayed fixture silently picked up a
    # completely different match's closing line. Odds here belong to a match
    # played the day BEFORE the fixture under prediction - they must be ignored
    # entirely, and the result must equal the Dixon-Coles-only fallback.
    _seed_two_team_world(db_conn, odds_match_date="2026-08-20")

    with_stale_odds = _blended_fixture_goals(db_conn, 1, 1, 2, _FIXTURE_DATE)

    assert with_stale_odds == _goals_without_odds(db_conn)


def test_malformed_odds_fall_back_to_dixon_coles_only(db_conn):
    # A single bad CSV row (decimal odds <= 1.0) must not abort the whole
    # projections run - devig raises ValueError and the fixture degrades to
    # Dixon-Coles-only, same as having no odds at all.
    _seed_two_team_world(db_conn, odds=(0.5, 5.0, 8.0, 1.7, 2.1))

    with_bad_odds = _blended_fixture_goals(db_conn, 1, 1, 2, _FIXTURE_DATE)

    assert with_bad_odds == _goals_without_odds(db_conn)
    assert expected_points(db_conn, 1).median > 0


def test_blended_fixture_goals_uses_live_odds_for_unplayed_fixture(db_conn):
    # A fixture with no match_results_history row (never played) but a
    # fixture_odds_live row - the fallback path, not the historical one.
    _seed_two_team_world(db_conn, with_player_stats=False)
    db_conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, updated_at) VALUES (2,'Gameweek 2','2026-08-28T17:30:00Z',1756400000,0,0,0,0,'t0')"
    )
    _insert_fixture(db_conn, 2, 2, 1, 2, date="2026-08-28")

    dc_only = _blended_fixture_goals(db_conn, 2, 1, 2, "2026-08-28")

    db_conn.execute(
        "INSERT INTO fixture_odds_live (fixture_id, source, bookmaker, home_win_odds, draw_odds, "
        "away_win_odds, over_2_5_odds, under_2_5_odds, retrieved_at) "
        "VALUES (2,'test','avg',1.5,4.5,6.0,1.8,2.0,'t0')"
    )
    db_conn.commit()

    with_live_odds = _blended_fixture_goals(db_conn, 2, 1, 2, "2026-08-28")

    # Proves the live-odds row was actually read and blended in, not ignored:
    # a lopsided home favourite (1.5 vs 4.5/6.0) moves the answer away from the
    # DC-only (weight=1.0) baseline computed before the row existed.
    assert with_live_odds != dc_only
    assert with_live_odds[0] > with_live_odds[1]


def test_blended_fixture_goals_historical_path_unaffected_by_live_table(db_conn):
    # Regression guard for this task's global constraint: a fixture that already
    # has a match_results_history + team_match_odds_history row must resolve via
    # the historical path only, even when fixture_odds_live also has a row for
    # the SAME fixture_id with clearly different odds.
    _seed_two_team_world(db_conn)

    historical_only = _blended_fixture_goals(db_conn, 1, 1, 2, _FIXTURE_DATE)

    db_conn.execute(
        "INSERT INTO fixture_odds_live (fixture_id, source, bookmaker, home_win_odds, draw_odds, "
        "away_win_odds, over_2_5_odds, under_2_5_odds, retrieved_at) "
        "VALUES (1,'test','avg',9.0,9.0,1.05,5.0,1.05,'t0')"
    )
    db_conn.commit()

    with_live_table_present = _blended_fixture_goals(db_conn, 1, 1, 2, _FIXTURE_DATE)

    assert with_live_table_present == historical_only


def test_player_share_is_normalized_to_per90_before_fixture_minutes(db_conn):
    # Regression for the double-discount bug: player_share_of_team_xg is an
    # ACCUMULATED ratio that already embeds the player's historical minutes
    # fraction, so multiplying it by this fixture's minutes fraction discounted
    # minutes twice and halved rotation players' goal projections.
    bootstrap = _bootstrap_two_teams_full_scoring()
    starter, rotation = dict(bootstrap["elements"][0]), dict(bootstrap["elements"][0])
    rotation.update({"id": 2, "code": 101, "web_name": "Rotation"})
    bootstrap["elements"] = [starter, rotation]
    _seed_full(db_conn, bootstrap, "t0")

    season = current_season(db_conn)
    arsenal = get_or_create_market_team(db_conn, "fpl", "Arsenal")
    # Same team, same per-90 xG (0.5). The starter plays all 10 team matches,
    # the rotation player only the first 5.
    for i in range(10):
        _insert_match_stat(db_conn, season, f"m{i}", 1, arsenal, f"2026-05-{10 + i:02d}", xg=0.5)
    for i in range(5):
        _insert_match_stat(db_conn, season, f"m{i}", 2, arsenal, f"2026-05-{10 + i:02d}", xg=0.5)

    starter_rates = _player_match_rates(db_conn, 1)
    rotation_rates = _player_match_rates(db_conn, 2)

    assert rotation_rates["historical_minutes_fraction"] == pytest.approx(0.5)
    assert starter_rates["historical_minutes_fraction"] == pytest.approx(1.0)
    # Accumulated shares differ by exactly the minutes ratio...
    assert rotation_rates["player_share"] == pytest.approx(starter_rates["player_share"] / 2)
    # ...but the per-90-equivalent share the goals term consumes must not.
    assert rotation_rates["player_share_per90"] == pytest.approx(starter_rates["player_share_per90"])


def test_n_gw_widens_the_fixture_window(db_conn):
    # n_gw is load-bearing again: it averages the fixture-level goals inputs over
    # the next n_gw fixtures. Without it, optimization/chips.py's wildcard
    # (n_gw=5) and free hit (n_gw=1) return byte-identical numbers.
    _seed_two_team_world(db_conn, with_player_stats=False)
    db_conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, updated_at) VALUES (2,'Gameweek 2','2026-08-28T17:30:00Z',1756400000,0,0,0,0,'t0')"
    )
    _insert_fixture(db_conn, 2, 2, 2, 1, date="2026-08-28")  # reverse fixture, player's team away

    one_gw = expected_points(db_conn, 1, n_gw=1)
    two_gw = expected_points(db_conn, 1, n_gw=2)

    assert one_gw.median != two_gw.median


def test_core_expected_points_is_leakage_free(db_conn):
    # Task 13's walk-forward backtest needs a reachable as_of_date path.
    # Adding matches AFTER the cutoff must not move an as-of-cutoff estimate.
    _seed_two_team_world(db_conn)
    season = current_season(db_conn)
    arsenal = get_or_create_market_team(db_conn, "fpl", "Arsenal")

    as_of = core_expected_points(db_conn, 1, as_of_date="2026-05-14")
    for i in range(6, 12):
        _insert_match_stat(db_conn, season, f"later{i}", 1, arsenal, f"2026-06-{10 + i:02d}", goals=3)
    unchanged = core_expected_points(db_conn, 1, as_of_date="2026-05-14")
    live = core_expected_points(db_conn, 1)

    assert as_of == unchanged
    assert live.goals > as_of.goals  # the later hot streak is visible in live mode only
    assert as_of.total == pytest.approx(as_of.appearance + as_of.goals + as_of.assists + as_of.cards, abs=1e-4)
    # 6 pre-cutoff matches -> the empirical (genuinely leakage-free) minutes
    # path. The flag must be reachable, because the OTHER path is not
    # leakage-free and the harness has to be able to tell them apart.
    assert as_of.minutes_source == "empirical"


def test_season_fallback_respects_before_season_and_does_not_leak(db_conn):
    """The season_shrunk_rate fallback (fired when Understat has zero rows for
    a player+season - the real, current condition) must respect the same
    leakage boundary every other query in this function already does. Without
    passing before_season through, a backtest of an earlier season would fall
    back to season_shrunk_rate's default "most recent row available" behavior
    - which could be a LATER, real season - leaking future performance into an
    "as of" historical estimate."""
    _seed_two_team_world(db_conn, with_player_stats=False)  # no Understat rows -> fallback fires

    # Two player_season_history rows for player 1: a modest earlier season and
    # an inflated later one. player_id=1 already has a '2025/26' row from
    # _seed_two_team_world's _insert_season_history call (goals_scored=0) -
    # overwrite it with a real, distinguishable value and add an earlier row.
    db_conn.execute("DELETE FROM player_season_history WHERE player_id=1")
    db_conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, "
        "goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (1,'2023/24',2700,30,0,5,2,0,0,10,0,0,3.0,0,0,0,50,55,'t0')"
    )
    db_conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, "
        "goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (1,'2025/26',2700,30,0,25,2,0,0,10,0,0,3.0,0,0,0,50,55,'t0')"
    )
    db_conn.commit()

    # Backtesting "2024-25": must see only the strictly-earlier 2023/24 row (5
    # goals), never the 2025/26 row (25 goals) - that would be real leakage.
    historical = core_expected_points(db_conn, 1, as_of_date="2024-06-01", season="2024-25")
    live = core_expected_points(db_conn, 1)  # live season has no rows of its own -> most recent available (2025/26)

    assert live.goals > historical.goals


def test_core_expected_points_falls_back_and_says_so(db_conn):
    # Fewer than _MIN_MATCHES_FOR_EMPIRICAL pre-cutoff matches -> minutes come
    # from expected_minutes(), which reads live players.status / the newest
    # stats snapshot / a live finished-event count and is NOT date-scoped. The
    # number is still returned, but minutes_source must admit which path ran so
    # the backtest can exclude or discount it.
    season, arsenal, _ = _seed_two_team_world(db_conn, with_player_stats=False)
    for i in range(2):
        _insert_match_stat(db_conn, season, f"m{i}", 1, arsenal, f"2026-05-{10 + i:02d}")

    assert core_expected_points(db_conn, 1, as_of_date="2026-05-14").minutes_source == "fallback_prior"


def test_core_expected_points_isolates_the_requested_season(db_conn):
    # A backtest replays a historical season against a DB that also holds the
    # LIVE season's rules. Without an explicit season, every query would filter
    # on current_season() and match zero historical rows - all-zero rates and a
    # fallback minutes prior, i.e. a plausible-looking meaningless number.
    bootstrap = _bootstrap_two_teams_full_scoring()
    # 2024-25's rules land FIRST so current_season() still returns the live
    # season, which is the shape the real DB actually has.
    sync_rules(db_conn, flatten_rules(bootstrap), "2024-25", "fpl_api_bootstrap", "t0")
    _seed_full(db_conn, bootstrap, "t0")
    live_season = current_season(db_conn)
    assert live_season != "2024-25"

    arsenal = get_or_create_market_team(db_conn, "fpl", "Arsenal")
    # Prolific in 2024-25, anonymous in the live season.
    for i in range(6):
        _insert_match_stat(db_conn, "2024-25", f"h{i}", 1, arsenal, f"2025-01-{10 + i:02d}", xg=0.9, goals=2)
    for i in range(6):
        _insert_match_stat(db_conn, live_season, f"c{i}", 1, arsenal, f"2026-05-{10 + i:02d}", xg=0.0, goals=0)

    historical = core_expected_points(db_conn, 1, as_of_date="2026-01-01", season="2024-25")
    live = core_expected_points(db_conn, 1)

    assert historical.season == "2024-25"
    assert historical.minutes_source == "empirical"  # the 6 pre-cutoff 2024-25 rows, not the fallback
    assert historical.goals > 0  # 2024-25 scoring rules AND 2024-25 goals both resolved
    assert historical.goals > live.goals

    # ...and the live season's rows cannot influence the historical answer.
    db_conn.execute("DELETE FROM player_match_stats_history WHERE season=?", (live_season,))
    db_conn.commit()

    assert core_expected_points(db_conn, 1, as_of_date="2026-01-01", season="2024-25") == historical


def test_null_bonus_in_season_history_does_not_crash(db_conn):
    # player_season_history.bonus is nullable and the normalizer writes None
    # through when history_past omits it; an unguarded division aborted the
    # whole player-pool loop with a TypeError.
    bootstrap = make_bootstrap()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420)
    db_conn.execute("UPDATE player_season_history SET bonus=NULL WHERE player_id=1")
    db_conn.commit()

    ep = expected_points(db_conn, 1)

    assert ep.median >= 0


def test_player_match_rates_bonus90_is_shrinkage_regressed_not_naive(db_conn):
    """Proves the wiring actually took effect - a test against _player_match_rates
    directly (not just bonus_regression.py in isolation), same lesson Plan 1a's
    final review taught this project: a pure function working correctly doesn't
    prove it's actually being called from the live path."""
    from fpl_agent.models.expected_points import _player_match_rates

    bootstrap = make_bootstrap()
    _seed_full(db_conn, bootstrap, "t0")
    # Target player: 1 match's worth of minutes, high bonus (naive would carry
    # this raw rate straight through with zero regression toward the population).
    _insert_season_history(db_conn, player_id=1, minutes=90, bonus=6)

    # A second FWD player.jt with a large sample forms a real, different population
    # prior - without this row position_average_bonus_per90 would just equal the
    # target's own rate and the test couldn't distinguish shrinkage from naive.
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (2,202,'BigSample',1,1,'a','t0')"
    )
    db_conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, "
        "goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (2,'2025/26',1800,20,0,0,0,0,0,18,0,0,0,0,0,0,50,55,'t0')"
    )
    db_conn.commit()

    rates = _player_match_rates(db_conn, player_id=1)

    naive_bonus90 = 6 / 90 * 90  # what the OLD code would have returned: 6.0
    assert rates["bonus90"] != naive_bonus90
    assert rates["bonus90"] < naive_bonus90  # pulled down toward the lower population prior


def test_player_match_rates_falls_back_to_season_history_when_understat_empty(db_conn):
    """Reproduces the real bug found live 2026-08-20: player_match_stats_history
    (Understat) had zero rows for every player on a fresh sync (fpl backfill-xg is
    broken - see CLAUDE.md), which silently collapsed goals/xa to 0.0 for
    literally every player (both the player's own rate AND the shrinkage prior
    come from the same empty table). This asserts the season_fallback path
    actually fires from the live _player_match_rates call, not just in
    player_regression.py's own unit tests in isolation - same lesson the bonus90
    test above already encodes for this exact class of bug."""
    bootstrap = make_bootstrap()
    _seed_full(db_conn, bootstrap, "t0")
    # No player_match_stats_history rows inserted at all for this season - the
    # real, current condition. player_season_history carries real goals/xA.
    db_conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, "
        "goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (1,'2025/26',2700,30,0,20,5,0,0,10,0,0,7.5,0,0,0,50,55,'t0')"
    )
    db_conn.commit()

    rates = _player_match_rates(db_conn, player_id=1)

    assert rates["goals_source"] == "season_fallback"
    assert rates["shrunk_goals90"] > 0.0  # was silently 0.0 before this fix, for every player
    assert rates["shrunk_xa90"] > 0.0
    assert rates["player_share_per90"] > 0.0

    ep = expected_points(db_conn, 1)
    assert ep.median > 2.0  # appearance points alone (~1.7-2.0 for a nailed starter) can't reach this
