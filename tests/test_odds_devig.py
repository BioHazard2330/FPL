import pytest

from fpl_agent.models.odds_devig import devig_match_odds, devig_totals_odds


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
