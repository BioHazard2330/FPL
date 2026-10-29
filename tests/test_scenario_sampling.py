

def test_bonus_follows_the_fixture_and_is_flat_at_the_league_average():
    import pytest
    from fpl_agent.models.scenario_sampling import (
        BONUS_REFERENCE_CLEAN_SHEET, BONUS_REFERENCE_GOALS, bonus_fixture_factor,
    )
    import math

    avg_opp = -math.log(BONUS_REFERENCE_CLEAN_SHEET)
    for pos in ("GKP", "DEF", "MID", "FWD"):
        assert bonus_fixture_factor(pos, BONUS_REFERENCE_GOALS, avg_opp) == pytest.approx(1.0)
    assert bonus_fixture_factor("FWD", 2.6, 1.0) > 1.4
    assert bonus_fixture_factor("FWD", 0.7, 1.0) < 0.7
    assert bonus_fixture_factor("DEF", 1.45, 0.6) > bonus_fixture_factor("DEF", 1.45, 2.0)
    assert bonus_fixture_factor("GKP", 3.0, avg_opp) == pytest.approx(1.0)
    assert bonus_fixture_factor("FWD", 0.0, 9.0) >= 0.1
