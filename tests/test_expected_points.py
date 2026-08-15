from fpl_agent.ingestion.market_identity import get_or_create_market_team
from fpl_agent.ingestion.sync import (
    _upsert_many,
    _extract_season,
    sync_rules,
    sync_stats_snapshot,
)
from fpl_agent.models.expected_points import MODEL_VERSION, expected_points
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


def _seed_market_history(conn, season, home_market_id, away_market_id):
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
        "home_goals, away_goals, source, retrieved_at) VALUES (?,'2026-08-20',?,?,2,0,'test','t0')",
        (season, home_market_id, away_market_id),
    )
    conn.execute(
        "INSERT INTO team_match_odds_history (match_id, source, bookmaker, home_win_odds, draw_odds, "
        "away_win_odds, over_2_5_odds, under_2_5_odds, retrieved_at) "
        "VALUES (?,'test','avg',1.4,5.0,8.0,1.7,2.1,'t0')",
        (cur.lastrowid,),
    )
    conn.commit()


def _seed_player_match_stats(conn, season, player_id, market_team_id):
    for i in range(6):
        conn.execute(
            "INSERT INTO player_match_stats_history (understat_match_id, understat_player_id, player_id, "
            "market_team_id, season, match_date, minutes, goals, assists, shots, xg, xa, key_passes, "
            "yellow_cards, red_cards, retrieved_at) VALUES (?,?,?,?,?,?,90,1,1,4,0.6,0.3,2,1,0,'t0')",
            (f"m{i}", f"u{player_id}", player_id, market_team_id, season, f"2026-05-{10 + i:02d}"),
        )
    conn.commit()


def test_expected_points_uses_blended_market_and_model_when_data_exists(db_conn):
    bootstrap = _bootstrap_two_teams_full_scoring()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420, bonus=25)
    db_conn.execute(
        "INSERT INTO fixtures (id,code,event,kickoff_time,team_h,team_a,team_h_score,team_a_score,"
        "team_h_difficulty,team_a_difficulty,finished,started,updated_at) "
        "VALUES (1,1,1,'2026-08-21T19:00:00Z',1,2,NULL,NULL,3,3,0,0,'t0')"
    )
    db_conn.commit()

    season = current_season(db_conn)
    arsenal = get_or_create_market_team(db_conn, "fpl", "Arsenal")
    chelsea = get_or_create_market_team(db_conn, "fpl", "Chelsea")
    _seed_market_history(db_conn, season, arsenal, chelsea)
    _seed_player_match_stats(db_conn, season, 1, arsenal)

    from fpl_agent.models.expected_points import _blended_fixture_goals

    team_goals, opp_goals = _blended_fixture_goals(db_conn, 1, 1, 2, "2026-08-21T19:00:00Z")

    # Proves the Dixon-Coles fit + devigged-odds blend actually ran: neither side
    # is the 1.3 league-average fallback, and the heavy home favourite in both
    # the results history and the odds shows up as team_goals >> opp_goals.
    assert team_goals != 1.3 and opp_goals != 1.3
    assert team_goals > opp_goals

    ep = expected_points(db_conn, 1)

    assert ep.model_version == MODEL_VERSION
    assert ep.floor <= ep.median <= ep.ceiling
    assert ep.median > 0
    # Shot-level data exists now, so the player's xG share is real, not the
    # zero-fallback the no-market-data test asserts.
    from fpl_agent.models.player_regression import player_share_of_team_xg

    assert player_share_of_team_xg(db_conn, 1, arsenal, season) > 0
