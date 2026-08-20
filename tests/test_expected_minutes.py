from fpl_agent.ingestion.sync import _upsert_many, sync_stats_snapshot
from fpl_agent.models.expected_minutes import expected_minutes
from fpl_agent.normalization.fpl_core import (
    normalize_element_types,
    normalize_events,
    normalize_player_stats,
    normalize_players,
    normalize_teams,
)

from test_sync import make_bootstrap


def _seed(conn, bootstrap, now):
    _upsert_many(conn, "teams", normalize_teams(bootstrap), now)
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), now)
    _upsert_many(conn, "events", normalize_events(bootstrap), now)
    _upsert_many(conn, "players", normalize_players(bootstrap), now)
    sync_stats_snapshot(conn, normalize_player_stats(bootstrap), now)
    conn.commit()


def _insert_season_history(conn, player_id, minutes=3420, starts=38, expected_goals=10.0, expected_assists=8.0, bonus=25):
    conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, goals_scored, "
        "assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (?,'2025/26',?,?,0,0,0,0,0,?,0,?,?,0,0,0,50,55,'t0')",
        (player_id, minutes, starts, bonus, expected_goals, expected_assists),
    )
    conn.commit()


def test_uses_last_season_prior_when_no_current_data(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420)

    result = expected_minutes(db_conn, 1)

    assert result.basis == "last_season_prior_no_current_data"
    assert result.confidence == "LOW"
    assert result.classification == "FIT"
    assert 85 <= result.expected_minutes <= 90  # 3420/38 = 90, capped, undamped (FIT)


def test_no_data_at_all_returns_zero(db_conn):
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")

    result = expected_minutes(db_conn, 1)

    assert result.basis == "no_data_available"
    assert result.expected_minutes == 0.0


def test_injury_damps_expected_minutes_to_zero(db_conn):
    bootstrap = make_bootstrap()
    bootstrap["elements"][0]["status"] = "i"
    bootstrap["elements"][0]["chance_of_playing_this_round"] = 0
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420)

    result = expected_minutes(db_conn, 1)

    assert result.classification == "CONFIRMED UNAVAILABLE"
    assert result.expected_minutes == 0.0


def test_cross_league_prior_used_when_genuinely_new_to_the_league(db_conn):
    """A brand-new signing with zero current-season AND zero PL history
    (real 2026-27 case: this transfer window's new arrivals) must still get
    a real, disclosed, LOW-confidence minutes estimate from their foreign-
    league prior rather than silently collapsing to zero - discounted for
    the genuine new-club minutes-share uncertainty."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")
    db_conn.execute(
        "INSERT INTO player_cross_league_prior (player_id, source_league, source_season, source_team_name, "
        "minutes, goals_per90, assists_per90, xg_per90, xa_per90, league_quality_factor, retrieved_at) "
        "VALUES (1,'La_liga','2025','Real Sociedad',3040,0.3,0.2,0.25,0.18,1.0,'t0')"
    )
    db_conn.commit()

    result = expected_minutes(db_conn, 1)

    assert result.basis == "cross_league_prior_new_signing"
    assert result.confidence == "LOW"
    # 3040/38 = 80.0 per-GW, discounted 0.6x = 48.0
    assert 47 <= result.expected_minutes <= 49


def test_cross_league_prior_absent_still_falls_back_to_zero(db_conn):
    """No PL history and no cross-league row either (e.g. a lower-league or
    non-top-5-league signing this project has no source for) - stays the
    honest zero, not a fabricated guess."""
    bootstrap = make_bootstrap()
    _seed(db_conn, bootstrap, "t0")

    result = expected_minutes(db_conn, 1)

    assert result.basis == "no_data_available"
    assert result.expected_minutes == 0.0


def test_doubtful_partially_damps_expected_minutes(db_conn):
    bootstrap = make_bootstrap()
    bootstrap["elements"][0]["status"] = "d"
    bootstrap["elements"][0]["chance_of_playing_this_round"] = 75
    _seed(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420)

    result = expected_minutes(db_conn, 1)

    assert result.classification == "DOUBTFUL"
    assert 0 < result.expected_minutes < 90
