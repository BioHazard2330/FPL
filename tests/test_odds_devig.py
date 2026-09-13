import pytest

from fpl_agent.models.odds_devig import devig_match_odds, devig_totals_odds, devig_two_outcome_prop


def test_devig_match_odds_removes_overround():
    probs = devig_match_odds(2.0, 3.5, 4.0)
    assert probs.home_win + probs.draw + probs.away_win == pytest.approx(1.0, abs=1e-9)
    assert probs.home_win > probs.draw > probs.away_win  # shortest odds -> highest probability


def test_devig_match_odds_rejects_invalid_odds():
    with pytest.raises(ValueError):
        devig_match_odds(1.0, 3.5, 4.0)


def test_devig_totals_odds_sums_to_one():
    probs = devig_totals_odds(1.9, 1.95)
    assert probs.over + probs.under == pytest.approx(1.0, abs=1e-9)
    assert probs.over > probs.under  # shorter odds on 'over' -> higher implied probability


def test_devig_two_outcome_prop_devigs_a_real_yes_no_pair():
    raw, devigged = devig_two_outcome_prop(2.0, 1.5)
    assert raw == 0.5
    assert devigged == round(0.5 / (0.5 + (1 / 1.5)), 4)
    assert devigged < raw  # a real vigged "Yes" price always overstates the true probability


def test_devig_two_outcome_prop_honest_none_without_a_real_complementary_price():
    raw, devigged = devig_two_outcome_prop(3.0, None)
    assert raw == round(1 / 3.0, 4)
    assert devigged is None
