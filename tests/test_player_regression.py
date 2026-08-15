from fpl_agent.models.player_regression import player_share_of_team_xg, player_shrunk_rates, shrink_rate


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


def test_position_average_per90_boundary_is_strict_less_than(db_conn):
    # match_date == as_of_date must be excluded (strictly before, not on-or-before) --
    # this is the exact leakage boundary Task 13's walk-forward backtest depends on.
    _seed_players_and_matches(db_conn)
    rates_on_boundary = player_shrunk_rates(db_conn, player_id=1, season="2024-25", as_of_date="2024-09-15")
    # matches on 2024-09-01 .. 2024-09-14 (14 matches) are strictly before 2024-09-15;
    # the 2024-09-15 match itself must be excluded
    assert rates_on_boundary["goals"].matches_played == 14.0
