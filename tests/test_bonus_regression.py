from fpl_agent.models.bonus_regression import (
    expected_bonus_per90,
    invalidate_cache_for_connection,
    position_average_bonus_per90,
)


def _seed_ref_data(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0')"
    )
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','t0')"
    )


def _seed_player(conn, player_id, web_name="P"):
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (?,?,?,1,1,'a','t0')",
        (player_id, player_id, web_name),
    )


def _insert_season_row(conn, player_id, season_name, bonus, minutes):
    conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, "
        "goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (?,?,?,0,0,0,0,0,0,?,0,0,0,0,0,0,50,55,'t0')",
        (player_id, season_name, minutes, bonus),
    )


def test_position_average_bonus_per90_computes_population_prior(db_conn):
    _seed_ref_data(db_conn)
    _seed_player(db_conn, 10, "BigSample")
    _seed_player(db_conn, 11, "SmallSample")
    _insert_season_row(db_conn, 10, "2023/24", bonus=36, minutes=1800)  # 20 matches, raw 1.8/90
    _insert_season_row(db_conn, 11, "2023/24", bonus=2, minutes=90)     # 1 match, raw 2.0/90
    db_conn.commit()

    result = position_average_bonus_per90(db_conn, "FWD")

    # SUM(bonus)/SUM(minutes/90) = 38 / 21 matches
    assert abs(result - 38 / 21) < 1e-9


def test_expected_bonus_per90_pulls_small_sample_toward_prior(db_conn):
    _seed_ref_data(db_conn)
    _seed_player(db_conn, 10, "BigSample")
    _seed_player(db_conn, 11, "SmallSample")
    _insert_season_row(db_conn, 10, "2023/24", bonus=36, minutes=1800)
    _insert_season_row(db_conn, 11, "2023/24", bonus=2, minutes=90)
    db_conn.commit()

    big = expected_bonus_per90(db_conn, 10)
    small = expected_bonus_per90(db_conn, 11)

    assert big.raw_per90 == 1.8
    assert small.raw_per90 == 2.0
    # Small sample (1 match) gets pulled meaningfully toward the ~1.81 population
    # prior; large sample (20 matches) barely moves from its own raw rate.
    assert small.shrunk_per90 == 1.8268
    assert big.shrunk_per90 == 1.8032
    assert abs(small.shrunk_per90 - small.raw_per90) > abs(big.shrunk_per90 - big.raw_per90)


def test_expected_bonus_per90_before_season_excludes_later_seasons(db_conn):
    _seed_ref_data(db_conn)
    _seed_player(db_conn, 10, "Multi")
    _insert_season_row(db_conn, 10, "2022/23", bonus=10, minutes=900)   # 10 matches, raw 1.0/90
    _insert_season_row(db_conn, 10, "2024/25", bonus=100, minutes=900)  # 10 matches, raw 10.0/90
    db_conn.commit()

    live = expected_bonus_per90(db_conn, 10)  # most recent overall -> 2024/25
    historical = expected_bonus_per90(db_conn, 10, before_season="2024/25")  # strictly before -> 2022/23

    assert live.raw_per90 == 10.0
    assert historical.raw_per90 == 1.0
    assert historical.raw_per90 < live.raw_per90


def test_expected_bonus_per90_no_prior_returns_pure_positional_average(db_conn):
    _seed_ref_data(db_conn)
    _seed_player(db_conn, 10, "HasData")
    _seed_player(db_conn, 12, "NoData")  # no player_season_history row at all
    _insert_season_row(db_conn, 10, "2023/24", bonus=18, minutes=900)  # 10 matches, raw 1.8/90
    db_conn.commit()

    result = expected_bonus_per90(db_conn, 12)

    # matches=0 -> shrink_rate's convex combination collapses to the prior exactly
    assert result.raw_per90 == 0.0
    assert result.shrunk_per90 == 1.8


def test_position_average_bonus_per90_is_cached_per_connection(db_conn):
    # Real perf fix, 2026-08-21: same population-prior caching gap as
    # player_regression.py::position_average_per90. Proves the cache is actually
    # hit (stale after an uninvalidated write) and invalidate_cache_for_connection
    # clears it.
    _seed_ref_data(db_conn)
    _seed_player(db_conn, 10, "BigSample")
    _insert_season_row(db_conn, 10, "2023/24", bonus=36, minutes=1800)
    db_conn.commit()

    first = position_average_bonus_per90(db_conn, "FWD")
    assert abs(first - 36 / 20) < 1e-9

    _seed_player(db_conn, 11, "SmallSample")
    _insert_season_row(db_conn, 11, "2023/24", bonus=2, minutes=90)
    db_conn.commit()

    assert position_average_bonus_per90(db_conn, "FWD") == first  # stale on purpose

    invalidate_cache_for_connection(db_conn)
    fresh = position_average_bonus_per90(db_conn, "FWD")
    assert abs(fresh - 38 / 21) < 1e-9
    assert fresh != first


def test_expected_bonus_per90_raises_for_unknown_player(db_conn):
    _seed_ref_data(db_conn)
    try:
        expected_bonus_per90(db_conn, 999)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "999" in str(e)
