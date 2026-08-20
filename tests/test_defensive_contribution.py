import math

from fpl_agent.models.defensive_contribution import (
    DEFCON_THRESHOLDS,
    defcon_points_probability,
    expected_defcon_actions_per90,
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
    # DEF threshold=10: P(X>=10) for a Poisson(9) - computed independently here,
    # not by re-deriving the module's own formula, to actually check the math.
    from scipy.stats import poisson
    rate = 9.0
    expected = sum(poisson.pmf(k, rate) for k in range(10, 60))
    result = defcon_points_probability(actions_per90=rate, position="DEF")
    assert math.isclose(result, expected, rel_tol=1e-6)


def test_mid_and_fwd_need_a_higher_rate_than_def_for_the_same_probability():
    # Same rate, different threshold (10 vs 12) - MID/FWD probability must be lower.
    rate = 10.0
    def_prob = defcon_points_probability(rate, "DEF")
    mid_prob = defcon_points_probability(rate, "MID")
    assert mid_prob < def_prob
