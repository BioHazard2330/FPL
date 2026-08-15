from fpl_agent.models.minutes_distribution import expected_appearance_points, minutes_bucket_probabilities


def _seed(conn, minutes_list, player_id=1):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (?,?,?,1,1,'a','2026-01-01T00:00:00Z')", (player_id, 200 + player_id, "Test"),
    )
    conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (1, 'Team A', 1)")
    rows = [
        (f"m{i}", f"p-{i}", player_id, 1, "2024-25", f"2024-09-{i+1:02d}", m, 0, 0, 0, 0.0, 0.0, 0, 0, 0)
        for i, m in enumerate(minutes_list)
    ]
    conn.executemany(
        "INSERT INTO player_match_stats_history "
        "(understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, "
        "minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'2026-01-01T00:00:00Z')",
        rows,
    )
    conn.commit()


def test_minutes_buckets_empirical_when_enough_matches(db_conn):
    _seed(db_conn, [90, 90, 90, 90, 90, 0, 90])  # 6 full, 1 zero -> mostly starts
    probs = minutes_bucket_probabilities(db_conn, player_id=1, season="2024-25")
    assert probs.source == "empirical"
    assert abs((probs.p_zero + probs.p_partial + probs.p_full) - 1.0) < 1e-9
    assert probs.p_full > probs.p_zero


def test_minutes_buckets_falls_back_with_too_few_matches(db_conn):
    _seed(db_conn, [90])  # only 1 match, below the empirical threshold
    probs = minutes_bucket_probabilities(db_conn, player_id=1, season="2024-25")
    assert probs.source == "fallback_prior"
    assert abs((probs.p_zero + probs.p_partial + probs.p_full) - 1.0) < 1e-6


def test_expected_appearance_points_weights_buckets_correctly():
    from fpl_agent.models.minutes_distribution import MinutesBucketProbabilities
    probs = MinutesBucketProbabilities(p_zero=0.1, p_partial=0.2, p_full=0.7, source="empirical")
    assert expected_appearance_points(probs) == 0.2 * 1.0 + 0.7 * 2.0


def test_minutes_buckets_as_of_date_excludes_future_rows(db_conn):
    # Sep 1-5 -> benched (0 mins), Sep 6-10 -> nailed starter (90 mins).
    _seed(db_conn, [0, 0, 0, 0, 0, 90, 90, 90, 90, 90])

    probs_live = minutes_bucket_probabilities(db_conn, player_id=1, season="2024-25")
    assert probs_live.p_full == 0.5
    assert probs_live.p_zero == 0.5

    # as_of_date="2024-09-06" must see only the 5 September 1-5 matches, strictly
    # excluding the Sep 6 match itself (boundary is exclusive, not inclusive) and
    # every match after it -> no future-data leakage into a backtest at that date.
    probs_asof = minutes_bucket_probabilities(db_conn, player_id=1, season="2024-25", as_of_date="2024-09-06")
    assert probs_asof.source == "empirical"
    assert probs_asof.p_zero == 1.0
    assert probs_asof.p_full == 0.0
