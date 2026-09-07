import pytest

from fpl_agent.backtesting.component_validation import validate_minutes_component, validate_rate_component
from test_backtest_harness import _seed_season


def test_validate_rate_component_rejects_unsupported_stat(db_conn):
    with pytest.raises(ValueError, match="unsupported rate component"):
        validate_rate_component(db_conn, "2024-25", "shots")


def test_validate_rate_component_produces_a_real_result(db_conn):
    _seed_season(db_conn)

    result = validate_rate_component(db_conn, "2024-25", "goals")

    assert result.stat == "goals"
    assert result.season == "2024-25"
    # 12 real matches, ROUND_SIZE=10 -> round 1 (dates 11-12) has 10 real
    # prior matches for the one seeded player - enough to cross the real
    # empirical gate (>=4) and be scored.
    assert result.sample_size > 0
    assert result.model_mae >= 0
    assert result.baseline_mae >= 0


def test_validate_rate_component_no_rows_when_nothing_crosses_the_empirical_gate(db_conn):
    """A season with real matches but never enough PRIOR history for any
    player to cross the real empirical gate must report a real, honest
    zero-sample result (fallback_excluded_count > 0), never a fabricated
    MAE from an empty comparison."""
    from test_backtest_harness import _seed_matches, _seed_player_matches, _seed_reference_data

    _seed_reference_data(db_conn)
    dates = ["2024-09-01", "2024-09-02"]  # only 2 real matches - never crosses the >=4 empirical bar
    _seed_matches(db_conn, dates)
    _seed_player_matches(db_conn, 1, dates, tag="m")
    db_conn.commit()

    result = validate_rate_component(db_conn, "2024-25", "goals")

    assert result.sample_size == 0
    assert result.fallback_excluded_count > 0


def test_validate_minutes_component_produces_a_real_result(db_conn):
    _seed_season(db_conn)

    result = validate_minutes_component(db_conn, "2024-25")

    assert result.season == "2024-25"
    assert result.sample_size > 0
    assert result.model_mae >= 0
    # Every seeded match is a real 90-minute appearance - a real, well-
    # calibrated minutes model should predict close to 90 for this player.
    assert result.model_mae < 30
