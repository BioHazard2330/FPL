from fpl_agent.models.player_regression import (
    invalidate_cache_for_connection,
    player_share_of_team_xg,
    player_shrunk_rates,
    position_average_per90,
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


def test_shrink_rate_prior_strength_override_pulls_harder_toward_the_prior():
    """`prior_strength` (2026-09-07, Phase 7.3 Part 4) - a real, opt-in
    override of the module default. A higher value must shrink harder
    (result closer to the prior, further from the player's own raw rate)."""
    default = shrink_rate(player_total=5.0, player_minutes=450, position_avg_per90=0.3)  # raw=1.0, prior=0.3
    stronger = shrink_rate(player_total=5.0, player_minutes=450, position_avg_per90=0.3, prior_strength=30.0)
    assert stronger.raw_per90 == default.raw_per90 == 1.0  # same real raw rate either way
    assert abs(stronger.shrunk_per90 - 1.0) > abs(default.shrunk_per90 - 1.0)


def test_goals_shrinkage_uses_the_real_fwd_override_not_other_positions(db_conn):
    """Real regression test for the Phase 7.3 Part 4 fix: a cross-season-
    validated walk-forward sweep (2025-26 AND 2024-25 seasons independently)
    found FWD goals need materially stronger shrinkage (k=30) than the
    project-wide default (k=10) - GKP/DEF/MID goals, and every position for
    assists/xG/xA, showed only noise-level differences and were NOT changed.
    This proves the override is scoped correctly: a FWD and a MID with the
    IDENTICAL raw goals rate and sample size must shrink to DIFFERENT values
    (the FWD pulled harder toward the prior), while their assists (not
    overridden) shrink identically."""
    from fpl_agent.models.player_regression import PRIOR_STRENGTH_MATCHES, shrink_rate

    conn = db_conn
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0'), (2,'Midfielder','MID','Midfielders','t0')"
    )
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','t0')")
    conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (1, 'Team A', 1)")
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (1,201,'FwdPlayer',1,1,'a','t0'), (2,202,'MidPlayer',1,2,'a','t0'), "
        "(3,203,'FwdPeer',1,1,'a','t0'), (4,204,'MidPeer',1,2,'a','t0')"
    )
    # Player 1 (FWD) and player 2 (MID): identical 5-match record (1 goal, 1 assist per
    # match) - only position differs. A "peer" at each position with 0 goals/0 assists gives
    # each position's own real population prior a genuine gap from the target's raw rate
    # (without a peer, a single-player position's own prior trivially equals its own raw
    # rate, making shrinkage a no-op regardless of k - the real bug the first version of
    # this test had).
    for pid in (1, 2):
        rows = [
            (f"m{pid}-{i}", f"p{pid}-{i}", pid, 1, "2024-25", f"2024-09-{i+1:02d}", 90, 1, 1, 3, 0.5, 0.3, 2, 0, 0)
            for i in range(5)
        ]
        conn.executemany(
            "INSERT INTO player_match_stats_history "
            "(understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, "
            "minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'t0')",
            rows,
        )
    for pid in (3, 4):
        rows = [
            (f"m{pid}-{i}", f"p{pid}-{i}", pid, 1, "2024-25", f"2024-09-{i+1:02d}", 90, 0, 0, 0, 0.0, 0.0, 0, 0, 0)
            for i in range(5)
        ]
        conn.executemany(
            "INSERT INTO player_match_stats_history "
            "(understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, "
            "minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'t0')",
            rows,
        )
    conn.commit()

    fwd_rates = player_shrunk_rates(conn, player_id=1, season="2024-25")
    mid_rates = player_shrunk_rates(conn, player_id=2, season="2024-25")

    assert fwd_rates["goals"].raw_per90 == mid_rates["goals"].raw_per90  # identical real raw rate
    # Same real position-average prior (both positions pool identical data here) but the FWD's
    # own goals shrink harder (k=30 vs k=10) - the two shrunk values must genuinely differ.
    assert fwd_rates["goals"].shrunk_per90 != mid_rates["goals"].shrunk_per90
    prior = position_average_per90(conn, "FWD", "goals", "2024-25")
    expected_fwd = shrink_rate(5.0, 450, prior, prior_strength=30.0).shrunk_per90
    expected_mid = shrink_rate(5.0, 450, prior, prior_strength=PRIOR_STRENGTH_MATCHES).shrunk_per90
    assert fwd_rates["goals"].shrunk_per90 == expected_fwd
    assert mid_rates["goals"].shrunk_per90 == expected_mid
    # Assists are NOT overridden for either position - must shrink identically.
    assert fwd_rates["assists"].shrunk_per90 == mid_rates["assists"].shrunk_per90


def test_player_shrunk_rates_small_sample_closer_to_average(db_conn):
    _seed_players_and_matches(db_conn)
    rates = player_shrunk_rates(db_conn, player_id=2, season="2024-25")
    assert rates["goals"].raw_per90 == 2.0
    # NOTE: brief's literal assertion here was `shrunk_per90 < 1.0`, which is mathematically
    # unsatisfiable given this fixture -- see task-10-report.md "Bug found" section for the proof.
    # shrunk_per90 is a convex combination of raw_per90 (2.0) and the position-average prior,
    # which (per the brief's un-excluded, population-mean form) is 17 goals / 16 matches =
    # 1.0625 -- that is the floor, so shrunk_per90 can never fall below 1.0625 for any positive
    # shrinkage strength. This fixture is FWD (`_seed_players_and_matches`'s own element_type),
    # so it now uses the real, cross-season-validated goals+FWD override (2026-09-07, Phase 7.3
    # Part 4 - `_GOALS_SHRINKAGE_STRENGTH_BY_POSITION`, k=30 not the module default k=10):
    # (1*2.0 + 30*1.0625) / 31 = 33.875/31 = 1.0927. Asserting against the player's own
    # raw_per90 instead of a magic constant tests the actual intended property: the 1-match
    # hot streak gets pulled down, well away from its raw rate, toward the position average -
    # MORE aggressively than the old k=10 value (1.1477) would have, per that real evidence.
    assert rates["goals"].shrunk_per90 < rates["goals"].raw_per90
    assert rates["goals"].shrunk_per90 == 1.0927
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
    # (15 + 10 + 2) goals / 17 matches = 27/17. This fixture is FWD, so goals shrinkage now
    # uses the real, cross-season-validated k=30 override (2026-09-07, Phase 7.3 Part 4 -
    # `_GOALS_SHRINKAGE_STRENGTH_BY_POSITION`), not the module default k=10:
    # shrunk_per90 = (16*1.5625 + 30*27/17)/46 = 1.5793
    assert rates_live["goals"].shrunk_per90 == 1.5793

    # as_of_date="2024-10-01" must see only the 15 September matches, strictly excluding
    # the December row (both from the player's own totals and from the position-average prior)
    assert rates_asof["goals"].matches_played == 15.0
    assert rates_asof["goals"].raw_per90 == 1.0
    assert rates_asof["goals"].raw_per90 < rates_live["goals"].raw_per90
    # prior computed via a separate query path than the player's own totals -- assert on
    # shrunk_per90 to prove that query is *also* date-filtered, not just the player's own totals.
    # With the Dec row excluded, prior = 17 goals / 16 matches = 1.0625 (not 27/17 = 1.5882).
    # This fixture is FWD, so goals shrinkage uses the k=30 override (see above):
    # shrunk_per90 = (15*1.0 + 30*1.0625)/45 = 1.0417, well below the live value.
    assert rates_asof["goals"].shrunk_per90 == 1.0417
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


def test_position_average_per90_is_cached_per_connection(db_conn):
    # Real perf fix, 2026-08-21: position_average_per90 is a pure (position, stat,
    # season, as_of_date) aggregate - cached rather than re-querying on every call.
    # Proves the cache actually short-circuits the query (second call sees stale
    # data after an uninvalidated write), then proves invalidate_cache_for_connection
    # clears it and a fresh query reflects the new row.
    _seed_players_and_matches(db_conn)
    first = position_average_per90(db_conn, "FWD", "goals", "2024-25")
    assert abs(first - 17 / 16) < 1e-9  # 15 (player1) + 2 (player2) goals / 16 matches

    # Insert another match without going through any writer that invalidates the
    # cache - a direct write, same as a test would do, simulating an out-of-band change.
    db_conn.execute(
        "INSERT INTO player_match_stats_history "
        "(understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, "
        "minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
        "VALUES ('m-new','p-new',1,1,'2024-25','2024-09-20',90,5,0,10,2.0,0.0,3,0,0,'2026-01-01T00:00:00Z')"
    )
    db_conn.commit()

    still_cached = position_average_per90(db_conn, "FWD", "goals", "2024-25")
    assert still_cached == first  # stale on purpose - proves the cache is actually hit, not a no-op

    invalidate_cache_for_connection(db_conn)
    fresh = position_average_per90(db_conn, "FWD", "goals", "2024-25")
    assert abs(fresh - 22 / 17) < 1e-9  # 17 + 5 new goals / 17 matches
    assert fresh != first


def test_position_average_per90_cache_keys_on_as_of_date_separately(db_conn):
    # Different as_of_date values must never share a cache entry - this is the
    # exact leakage boundary the walk-forward backtest depends on.
    _seed_players_and_matches(db_conn)
    live = position_average_per90(db_conn, "FWD", "goals", "2024-25", as_of_date=None)
    asof = position_average_per90(db_conn, "FWD", "goals", "2024-25", as_of_date="2024-09-15")
    assert live != asof
    # re-querying each returns the same cached value it returned the first time
    assert position_average_per90(db_conn, "FWD", "goals", "2024-25", as_of_date=None) == live
    assert position_average_per90(db_conn, "FWD", "goals", "2024-25", as_of_date="2024-09-15") == asof


def test_season_position_average_per90_is_cached_per_connection(db_conn):
    conn = db_conn
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0')"
    )
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','t0')")
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (10,10,'P10',1,1,'a','t0')"
    )
    _seed_season_history(conn, 10, "2023/24", goals_scored=18, expected_assists=0, minutes=900)
    conn.commit()

    first = season_position_average_per90(conn, "FWD", "goals_scored")
    assert abs(first - 18 / 10) < 1e-9

    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (11,11,'P11',1,1,'a','t0')"
    )
    _seed_season_history(conn, 11, "2023/24", goals_scored=9, expected_assists=0, minutes=900)
    conn.commit()

    assert season_position_average_per90(conn, "FWD", "goals_scored") == first  # still cached, stale on purpose

    invalidate_cache_for_connection(conn)
    fresh = season_position_average_per90(conn, "FWD", "goals_scored")
    assert abs(fresh - 27 / 20) < 1e-9
    assert fresh != first


def test_position_average_per90_boundary_is_strict_less_than(db_conn):
    # match_date == as_of_date must be excluded (strictly before, not on-or-before) --
    # this is the exact leakage boundary Task 13's walk-forward backtest depends on.
    _seed_players_and_matches(db_conn)
    rates_on_boundary = player_shrunk_rates(db_conn, player_id=1, season="2024-25", as_of_date="2024-09-15")
    # matches on 2024-09-01 .. 2024-09-14 (14 matches) are strictly before 2024-09-15;
    # the 2024-09-15 match itself must be excluded
    assert rates_on_boundary["goals"].matches_played == 14.0
