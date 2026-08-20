from fpl_agent.models.player_regression import (
    player_share_of_team_xg,
    player_shrunk_rates,
    season_position_average_per90,
    season_shrunk_rate,
    shrink_rate,
)


def _seed_players_and_matches(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','2026-01-01T00:00:00Z')"
    )
    for pid, web in ((1, "Prolific"), (2, "SmallSample")):
        conn.execute(
            "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
            "VALUES (?,?,?,1,1,'a','2026-01-01T00:00:00Z')", (pid, 200 + pid, web),
        )
    conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (1, 'Team A', 1)")

    rows = []
    for i in range(15):  # player 1: consistent, high-volume scorer
        rows.append((f"m{i}", f"p1-{i}", 1, 1, "2024-25", f"2024-09-{i+1:02d}", 90, 1, 0, 3, 0.8, 0.1, 2, 0, 0))
    rows.append(("m99", "p2-0", 2, 1, "2024-25", "2024-09-01", 90, 2, 0, 5, 1.5, 0.0, 1, 0, 0))  # player 2: 1 match, hot streak

    conn.executemany(
        "INSERT INTO player_match_stats_history "
        "(understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, "
        "minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'2026-01-01T00:00:00Z')",
        rows,
    )
    conn.commit()


def test_shrink_rate_pulls_small_sample_toward_prior():
    small_sample = shrink_rate(player_total=2.0, player_minutes=90, position_avg_per90=0.3)
    large_sample = shrink_rate(player_total=15.0, player_minutes=1350, position_avg_per90=0.3)
    assert small_sample.raw_per90 == 2.0
    assert small_sample.shrunk_per90 < small_sample.raw_per90
    assert abs(large_sample.shrunk_per90 - large_sample.raw_per90) < abs(small_sample.shrunk_per90 - small_sample.raw_per90)


def test_player_shrunk_rates_small_sample_closer_to_average(db_conn):
    _seed_players_and_matches(db_conn)
    rates = player_shrunk_rates(db_conn, player_id=2, season="2024-25")
    assert rates["goals"].raw_per90 == 2.0
    # NOTE: brief's literal assertion here was `shrunk_per90 < 1.0`, which is mathematically
    # unsatisfiable given this fixture -- see task-10-report.md "Bug found" section for the proof.
    # shrunk_per90 is a convex combination of raw_per90 (2.0) and the position-average prior,
    # which (per the brief's un-excluded, population-mean form) is 17 goals / 16 matches =
    # 1.0625 -- that is the floor, so shrunk_per90 can never fall below 1.0625 for any
    # PRIOR_STRENGTH_MATCHES > 0. With PRIOR_STRENGTH_MATCHES=10 the exact value is
    # (1*2.0 + 10*1.0625) / 11 = 12.625/11 = 1.1477. Asserting against the player's own
    # raw_per90 instead of a magic constant tests the actual intended property: the 1-match
    # hot streak gets pulled down, well away from its raw rate, toward the position average.
    assert rates["goals"].shrunk_per90 < rates["goals"].raw_per90
    assert rates["goals"].shrunk_per90 == 1.1477
    assert rates["goals"].shrunk_per90 < 1.5  # meaningfully pulled down, not just barely


def test_player_share_of_team_xg(db_conn):
    _seed_players_and_matches(db_conn)
    share = player_share_of_team_xg(db_conn, player_id=1, market_team_id=1, season="2024-25")
    assert 0 < share < 1


def test_player_shrunk_rates_includes_cards(db_conn):
    _seed_players_and_matches(db_conn)
    rates = player_shrunk_rates(db_conn, player_id=1, season="2024-25")
    assert "cards" in rates
    assert rates["cards"].shrunk_per90 >= 0


def test_player_shrunk_rates_as_of_date_excludes_future_rows(db_conn):
    _seed_players_and_matches(db_conn)
    # A big-outburst match dated after the seeded September matches -- must not leak into
    # a backtest that is only supposed to see data strictly before 2024-10-01.
    db_conn.execute(
        "INSERT INTO player_match_stats_history "
        "(understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, "
        "minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
        "VALUES ('m-future','p1-future',1,1,'2024-25','2024-12-01',90,10,0,20,5.0,0.0,5,0,0,'2026-01-01T00:00:00Z')"
    )
    db_conn.commit()

    rates_live = player_shrunk_rates(db_conn, player_id=1, season="2024-25")
    rates_asof = player_shrunk_rates(db_conn, player_id=1, season="2024-25", as_of_date="2024-10-01")

    # live (as_of_date=None) sees all 16 matches including the Dec outburst
    assert rates_live["goals"].matches_played == 16.0
    assert rates_live["goals"].raw_per90 == (15 + 10) / 16
    # position-average prior (population mean, no exclusion) over all rows in the pool:
    # (15 + 10 + 2) goals / 17 matches = 27/17 -> shrunk_per90 = (16*1.5625 + 10*27/17)/26 = 1.5724
    assert rates_live["goals"].shrunk_per90 == 1.5724

    # as_of_date="2024-10-01" must see only the 15 September matches, strictly excluding
    # the December row (both from the player's own totals and from the position-average prior)
    assert rates_asof["goals"].matches_played == 15.0
    assert rates_asof["goals"].raw_per90 == 1.0
    assert rates_asof["goals"].raw_per90 < rates_live["goals"].raw_per90
    # prior computed via a separate query path than the player's own totals -- assert on
    # shrunk_per90 to prove that query is *also* date-filtered, not just the player's own totals.
    # With the Dec row excluded, prior = 17 goals / 16 matches = 1.0625 (not 27/17 = 1.5882),
    # so shrunk_per90 = (15*1.0 + 10*1.0625)/25 = 1.025, well below the live value.
    assert rates_asof["goals"].shrunk_per90 == 1.025
    assert rates_asof["goals"].shrunk_per90 < rates_live["goals"].shrunk_per90


def _seed_season_history(conn, player_id, season_name, goals_scored, expected_assists, minutes):
    conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, "
        "goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (?,?,?,0,0,?,0,0,0,0,0,0,?,0,0,0,50,55,'t0')",
        (player_id, season_name, minutes, goals_scored, expected_assists),
    )


def test_season_position_average_per90_computes_population_prior(db_conn):
    conn = db_conn
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0')"
    )
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','t0')")
    for pid in (10, 11):
        conn.execute(
            "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
            "VALUES (?,?,?,1,1,'a','t0')", (pid, pid, f"P{pid}"),
        )
    _seed_season_history(conn, 10, "2023/24", goals_scored=18, expected_assists=0, minutes=900)  # 10 matches
    _seed_season_history(conn, 11, "2023/24", goals_scored=2, expected_assists=0, minutes=90)     # 1 match
    conn.commit()

    result = season_position_average_per90(conn, "FWD", "goals_scored")

    assert abs(result - 20 / 11) < 1e-9


def test_season_position_average_per90_rejects_unknown_column(db_conn):
    try:
        season_position_average_per90(db_conn, "FWD", "bps")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "bps" in str(e)


def test_season_shrunk_rate_pulls_small_sample_toward_prior(db_conn):
    conn = db_conn
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0')"
    )
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','t0')")
    for pid in (10, 11):
        conn.execute(
            "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
            "VALUES (?,?,?,1,1,'a','t0')", (pid, pid, f"P{pid}"),
        )
    _seed_season_history(conn, 10, "2023/24", goals_scored=18, expected_assists=0, minutes=900)   # 10 matches, 1.8/90
    _seed_season_history(conn, 11, "2023/24", goals_scored=2, expected_assists=0, minutes=90)      # 1 match, 2.0/90
    conn.commit()

    big = season_shrunk_rate(conn, 10, "goals_scored")
    small = season_shrunk_rate(conn, 11, "goals_scored")

    assert big.raw_per90 == 1.8
    assert small.raw_per90 == 2.0
    assert abs(small.shrunk_per90 - small.raw_per90) > abs(big.shrunk_per90 - big.raw_per90)


def test_season_shrunk_rate_no_data_returns_pure_positional_average(db_conn):
    conn = db_conn
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0')"
    )
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','t0')")
    for pid in (10, 12):
        conn.execute(
            "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
            "VALUES (?,?,?,1,1,'a','t0')", (pid, pid, f"P{pid}"),
        )
    _seed_season_history(conn, 10, "2023/24", goals_scored=18, expected_assists=0, minutes=900)  # 10 matches, 1.8/90
    conn.commit()

    result = season_shrunk_rate(conn, 12, "goals_scored")  # player 12 has no season_history row at all

    assert result.raw_per90 == 0.0
    assert result.shrunk_per90 == 1.8


def test_season_shrunk_rate_raises_for_unknown_player(db_conn):
    conn = db_conn
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0')"
    )
    try:
        season_shrunk_rate(conn, 999, "goals_scored")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "999" in str(e)


def test_position_average_per90_boundary_is_strict_less_than(db_conn):
    # match_date == as_of_date must be excluded (strictly before, not on-or-before) --
    # this is the exact leakage boundary Task 13's walk-forward backtest depends on.
    _seed_players_and_matches(db_conn)
    rates_on_boundary = player_shrunk_rates(db_conn, player_id=1, season="2024-25", as_of_date="2024-09-15")
    # matches on 2024-09-01 .. 2024-09-14 (14 matches) are strictly before 2024-09-15;
    # the 2024-09-15 match itself must be excluded
    assert rates_on_boundary["goals"].matches_played == 14.0
