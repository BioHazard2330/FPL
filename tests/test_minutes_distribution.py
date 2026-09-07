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


def _seed_second_player(conn, minutes_list, player_id):
    """A second real FWD in the same fixture DB, so the positional-average
    prior differs from the first player's own raw rate - real shrinkage
    can only be observed/tested when the population isn't just the one
    player being measured."""
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (?,?,?,1,1,'a','2026-01-01T00:00:00Z')", (player_id, 200 + player_id, f"Test{player_id}"),
    )
    rows = [
        (f"m{player_id}-{i}", f"p-{player_id}-{i}", player_id, 1, "2024-25", f"2024-09-{i+1:02d}",
         m, 0, 0, 0, 0.0, 0.0, 0, 0, 0)
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


def test_empirical_bucket_shrinks_toward_a_real_positional_average(db_conn):
    """Real calibration fix (2026-09-02): a thin, noisy raw frequency (this
    player's own last 4 matches: 3 benched, 1 start) must be pulled toward
    the real positional average from every OTHER FWD in the DB (here, all
    nailed starters) - never taken at bare face value the way the old
    zero-shrinkage code did. Confirms the fix is actually active, not just
    a no-op in the single-player fixture the other tests use."""
    _seed(db_conn, [0, 0, 0, 90], player_id=1)  # this player's own raw p_full = 0.25
    for pid in (2, 3, 4, 5):
        _seed_second_player(db_conn, [90, 90, 90, 90, 90, 90, 90, 90, 90, 90], player_id=pid)  # always starts

    probs = minutes_bucket_probabilities(db_conn, player_id=1, season="2024-25")

    assert probs.source == "empirical"
    # Raw would be 0.25; shrunk toward the population's much higher rate must
    # land strictly between the two, materially above the bare raw value.
    assert 0.25 < probs.p_full < 1.0
    assert probs.p_zero < 0.75


def test_fringe_player_shrinks_toward_a_fringe_tier_prior_not_the_starter_heavy_blanket_average(db_conn):
    """Real regression test for the Phase 7.3 minutes-model fix - a real,
    measured bug found via walk-forward diagnostic against the 2025-26
    season: the OLD blanket position-wide prior is dominated by established-
    starter rows (most real minutes at any position come from the 11 who
    start), so shrinking a genuinely fringe player toward it systematically
    overpredicted fringe minutes (measured +17.4 real average minutes bias).
    This player's own raw rate (2 of 8 matches full = 0.25, right at the
    fringe/rotational boundary - "fringe" per `_minutes_tier`) must now
    shrink toward the OTHER real fringe players in the population, not the
    established starters also present - landing much closer to this
    player's own raw rate than the old blanket-average fix would have."""
    from fpl_agent.models.minutes_distribution import (
        _position_average_minutes_buckets,
        _position_tier_average_minutes_buckets,
    )

    _seed(db_conn, [0, 0, 0, 0, 0, 0, 90, 0], player_id=1)  # raw p_full = 0.125 -> fringe tier
    # 25 more real fringe players (>= _MIN_ROWS_FOR_TIER_PRIOR=20 real rows) so the
    # tier-conditioned prior can activate rather than falling back to blanket.
    for pid in range(2, 27):
        _seed_second_player(db_conn, [0, 0, 0, 0, 0, 0, 0, 0], player_id=pid)  # always benched
    # A handful of established starters too, so the BLANKET average (which pools
    # everyone) would be pulled up - proving the fix isn't a no-op in this fixture.
    for pid in range(27, 32):
        _seed_second_player(db_conn, [90, 90, 90, 90, 90, 90, 90, 90], player_id=pid)

    blanket = _position_average_minutes_buckets(db_conn, "FWD", "2024-25")
    fringe_prior = _position_tier_average_minutes_buckets(db_conn, "FWD", "fringe", "2024-25")
    assert fringe_prior is not None
    assert fringe_prior[2] < blanket[2]  # fringe-tier full-match rate genuinely lower than the pooled blanket rate

    probs = minutes_bucket_probabilities(db_conn, player_id=1, season="2024-25")
    assert probs.source == "empirical"
    # Shrunk toward the fringe-tier prior (~0.0 full-match rate among 25 always-
    # benched peers), not the starter-inflated blanket - stays close to this
    # player's own low raw rate (0.125), never pulled toward the established
    # starters' 90-minute rate the way the old blanket prior would.
    assert probs.p_full < 0.2


def _seed_matches_on_dates(conn, player_id, dates_and_minutes):
    rows = [
        (f"m{player_id}-{i}", f"p-{player_id}-{i}", player_id, 1, "2024-25", d, m, 0, 0, 0, 0.0, 0.0, 0, 0, 0)
        for i, (d, m) in enumerate(dates_and_minutes)
    ]
    conn.executemany(
        "INSERT INTO player_match_stats_history "
        "(understat_match_id, understat_player_id, player_id, market_team_id, season, match_date, "
        "minutes, goals, assists, shots, xg, xa, key_passes, yellow_cards, red_cards, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'2026-01-01T00:00:00Z')",
        rows,
    )
    conn.commit()


def test_returning_after_absence_shrinks_toward_a_real_return_window_prior_not_the_stale_established_tier(db_conn):
    """Real, measured fix, Phase 7.4 Part 8/11 minutes audit - a real
    walk-forward segment audit found RETURNING_AFTER_ABSENCE the single
    largest, most consistent minutes-bias segment across every real
    backtestable season tested (+19.48/+10.75/+10.49 average minutes
    overprediction). The target player's own trailing-<=10-match raw
    sample is STALE (5 real full-90 matches before a real 29-day gap) -
    the OLD code would classify this as "established" (median/full-rate
    both high) and leave it on the blanket prior, missing the real
    absence entirely. The fix must instead detect the real gap and shrink
    toward a real, measured "returning" population prior (built here from
    20 other real players' own low-minute first match back after their
    OWN real gap) - landing materially below the stale established
    reading."""
    conn = db_conn
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0')"
    )
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','t0')")
    conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (1, 'Team A', 1)")
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (1,201,'Target',1,1,'a','t0')"
    )
    # Real, established pre-absence pattern (5 real full-90 matches), then a
    # real 29-day gap before the scored round.
    _seed_matches_on_dates(conn, 1, [
        ("2024-07-01", 90), ("2024-07-08", 90), ("2024-07-15", 90), ("2024-07-22", 90), ("2024-07-29", 90),
    ])
    as_of_date = "2024-08-27"  # 29 real days after the last 2024-07-29 match

    # 20 real peers, each with an early match, a real >=21-day gap, then a
    # real LOW-minute return match (eased back in) - the real population
    # this player's own return should shrink toward.
    for pid in range(2, 22):
        conn.execute(
            "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
            "VALUES (?,?,?,1,1,'a','t0')", (pid, 200 + pid, f"Peer{pid}"),
        )
        _seed_matches_on_dates(conn, pid, [("2024-06-01", 90), ("2024-07-01", 15)])  # 30-day gap, real eased-back cameo

    from fpl_agent.models.minutes_distribution import _minutes_tier
    # Sanity: confirm this fixture really would have classified as
    # "established" under the OLD tier logic (median of trailing 5 = 90).
    assert _minutes_tier(1.0) == "established"

    probs = minutes_bucket_probabilities(db_conn, player_id=1, season="2024-25", as_of_date=as_of_date)

    assert probs.source == "empirical"
    # A stale "established" reading would keep p_full near 1.0 (5/5 real
    # trailing matches were full 90s) - the real fix must pull this
    # materially down toward the real returning-population's own low rate.
    assert probs.p_full < 0.7


def test_is_returning_after_absence_detects_a_real_gap(db_conn):
    from fpl_agent.models.minutes_distribution import _is_returning_after_absence

    conn = db_conn
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0')"
    )
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,100,'Team A','TMA','t0')")
    conn.execute("INSERT INTO market_teams (id, canonical_name, fpl_team_id) VALUES (1, 'Team A', 1)")
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (1,201,'Target',1,1,'a','t0')"
    )
    _seed_matches_on_dates(conn, 1, [("2024-07-01", 90)])

    assert _is_returning_after_absence(conn, 1, "2024-25", "2024-07-25") is True  # 24-day real gap
    assert _is_returning_after_absence(conn, 1, "2024-25", "2024-07-05") is False  # only a 4-day real gap
    assert _is_returning_after_absence(conn, 1, "2024-25", "2024-06-01") is False  # no real prior match at all yet


def test_position_average_prior_is_leakage_free(db_conn):
    """The positional-average prior itself must respect as_of_date - a
    population prior that leaked future rows in would corrupt the walk-
    forward backtest's own leakage-free guarantee just as surely as the
    per-player raw frequency would."""
    _seed(db_conn, [0, 0, 0, 0, 0], player_id=1)  # thin/benched sample as of the cutoff
    # A second FWD who only starts scoring big minutes AFTER the cutoff -
    # must never influence the as_of_date-scoped prior.
    _seed_second_player(db_conn, [0, 0, 0, 0, 0, 90, 90, 90, 90, 90], player_id=2)

    probs_asof = minutes_bucket_probabilities(db_conn, player_id=1, season="2024-25", as_of_date="2024-09-06")

    # Every real row before the cutoff (both players) is 0 minutes - the
    # leakage-free prior must therefore still be all-zero, not pulled up by
    # player 2's real but FUTURE (post-cutoff) starts.
    assert probs_asof.p_full == 0.0
    assert probs_asof.p_zero == 1.0
