import math

from fpl_agent.models.defensive_contribution import (
    DEFCON_THRESHOLDS,
    defcon_points_probability,
    expected_defcon_actions_per90,
    invalidate_cache_for_connection,
    position_average_defcon_per90,
)


def _seed_ref_data(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Defender','DEF','Defenders','t0')"
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


def _insert_season_row(conn, player_id, season_name, defcon, minutes):
    conn.execute(
        "INSERT INTO player_season_history (player_id, season_name, minutes, starts, total_points, "
        "goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, expected_goals, expected_assists, "
        "expected_goal_involvements, expected_goals_conceded, defensive_contribution, start_cost, end_cost, retrieved_at) "
        "VALUES (?,?,?,0,0,0,0,0,0,0,0,0,0,0,0,?,50,55,'t0')",
        (player_id, season_name, minutes, defcon),
    )


def test_position_average_defcon_per90_computes_population_prior(db_conn):
    _seed_ref_data(db_conn)
    _seed_player(db_conn, 10, "BigSample")
    _seed_player(db_conn, 11, "SmallSample")
    _insert_season_row(db_conn, 10, "2025/26", defcon=450, minutes=3600)  # 40 matches, 11.25/90
    _insert_season_row(db_conn, 11, "2025/26", defcon=10, minutes=90)     # 1 match, 10.0/90
    db_conn.commit()

    result = position_average_defcon_per90(db_conn, "DEF")

    assert abs(result - (460 / (3690 / 90))) < 1e-9


def test_expected_defcon_actions_per90_shrinks_small_sample_toward_prior(db_conn):
    _seed_ref_data(db_conn)
    _seed_player(db_conn, 10, "BigSample")
    _seed_player(db_conn, 11, "SmallSample")
    _insert_season_row(db_conn, 10, "2025/26", defcon=360, minutes=3600)  # 9.0/90, large sample
    _insert_season_row(db_conn, 11, "2025/26", defcon=20, minutes=90)     # 20.0/90, 1 match - hot streak

    result = expected_defcon_actions_per90(db_conn, player_id=11)

    assert result.raw_per90 == 20.0
    assert result.shrunk_per90 < result.raw_per90  # pulled down toward the population prior


def test_expected_defcon_actions_per90_leakage_free_with_before_season(db_conn):
    _seed_ref_data(db_conn)
    _seed_player(db_conn, 10)
    _insert_season_row(db_conn, 10, "2024/25", defcon=180, minutes=1800)  # 9.0/90
    _insert_season_row(db_conn, 10, "2025/26", defcon=900, minutes=1800)  # 45.0/90 - a future season
    db_conn.commit()

    result = expected_defcon_actions_per90(db_conn, player_id=10, before_season="2025/26")

    assert result.raw_per90 == 9.0  # only the 2024/25 row, the later season must not leak in


def test_position_average_defcon_per90_is_cached_per_connection(db_conn):
    # Real perf fix, 2026-08-21: same population-prior caching gap as
    # player_regression.py::position_average_per90. Proves the cache is actually
    # hit (stale after an uninvalidated write) and invalidate_cache_for_connection
    # clears it.
    _seed_ref_data(db_conn)
    _seed_player(db_conn, 10, "BigSample")
    _insert_season_row(db_conn, 10, "2025/26", defcon=450, minutes=3600)
    db_conn.commit()

    first = position_average_defcon_per90(db_conn, "DEF")
    assert abs(first - 450 / 40) < 1e-9

    _seed_player(db_conn, 11, "SmallSample")
    _insert_season_row(db_conn, 11, "2025/26", defcon=10, minutes=90)
    db_conn.commit()

    assert position_average_defcon_per90(db_conn, "DEF") == first  # stale on purpose

    invalidate_cache_for_connection(db_conn)
    fresh = position_average_defcon_per90(db_conn, "DEF")
    assert abs(fresh - 460 / 41) < 1e-9
    assert fresh != first


def test_defcon_points_probability_gkp_is_always_zero():
    assert DEFCON_THRESHOLDS["GKP"] is None
    assert defcon_points_probability(actions_per90=15.0, position="GKP") == 0.0


def test_defcon_points_probability_zero_rate_is_zero():
    assert defcon_points_probability(actions_per90=0.0, position="DEF") == 0.0


def test_defcon_points_probability_increases_with_rate():
    low = defcon_points_probability(actions_per90=3.0, position="DEF")
    high = defcon_points_probability(actions_per90=15.0, position="DEF")
    assert 0.0 <= low < high <= 1.0


def test_defcon_points_probability_matches_poisson_survival_function_directly():
    # MID threshold=12: P(X>=12) for a Poisson(11) - computed independently here,
    # not by re-deriving the module's own formula, to actually check the math.
    from scipy.stats import poisson
    rate = 11.0
    expected = sum(poisson.pmf(k, rate) for k in range(12, 70))
    result = defcon_points_probability(actions_per90=rate, position="MID")
    assert math.isclose(result, expected, rel_tol=1e-6)


def test_a_defenders_count_is_spread_wider_than_poisson():
    # DEF threshold=10 with a mean of 7 and variance 1.3x the mean (measured): the
    # distribution used has that mean and variance, and puts more weight above a
    # threshold the mean falls well short of than a Poisson would.
    from scipy.stats import nbinom, poisson
    p = 1 / 1.3
    n = 7.0 * p / (1 - p)
    assert math.isclose(nbinom.mean(n, p), 7.0, rel_tol=1e-9)
    assert math.isclose(nbinom.var(n, p), 7.0 * 1.3, rel_tol=1e-9)
    expected = sum(nbinom.pmf(k, n, p) for k in range(10, 80))
    result = defcon_points_probability(actions_per90=7.0, position="DEF")
    assert math.isclose(result, expected, rel_tol=1e-6)
    assert result > sum(poisson.pmf(k, 7.0) for k in range(10, 60))


def test_mid_and_fwd_need_a_higher_rate_than_def_for_the_same_probability():
    # Same rate, different threshold (10 vs 12) - MID/FWD probability must be lower.
    rate = 10.0
    def_prob = defcon_points_probability(rate, "DEF")
    mid_prob = defcon_points_probability(rate, "MID")
    assert mid_prob < def_prob


def test_this_seasons_matches_count_four_times_in_the_rate(db_conn, monkeypatch):
    from fpl_agent.models import defensive_contribution as dc
    from fpl_agent.models import rules

    import pytest

    _seed_ref_data(db_conn)
    _seed_player(db_conn, 1)
    _insert_season_row(db_conn, 1, "2025/26", defcon=80, minutes=900)
    monkeypatch.setattr(rules, "current_season", lambda conn: "2026-27")
    before = dc.expected_defcon_actions_per90(db_conn, 1)
    season = "2026-27"
    db_conn.execute(
        "INSERT INTO player_gw_stats (player_id, event, season, minutes, starts, goals, assists, clean_sheets, goals_conceded, "
        "own_goals, penalties_missed, penalties_saved, yellow_cards, red_cards, saves, bonus, bps, defensive_contribution, "
        "xg, xa, xgc, total_points, fixtures, retrieved_at) "
        "VALUES (1, 1, ?, 180, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 30, 0, 0, 0, 4, 2, 't0')", (season,),
    )
    after = dc.expected_defcon_actions_per90(db_conn, 1)
    assert after.shrunk_per90 > before.shrunk_per90
    assert after.raw_per90 == pytest.approx((80 + 4 * 30) / ((900 + 4 * 180) / 90))
    assert dc.expected_defcon_actions_per90(db_conn, 1, before_season="2026/27").shrunk_per90 == pytest.approx(before.shrunk_per90)
