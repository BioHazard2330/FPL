from fpl_agent.backtesting.plan_replay import _with_club_ids
from fpl_agent.optimization.squad import PlayerCandidate


def _c(pid, team_short):
    return PlayerCandidate(player_id=pid, web_name=str(pid), position="MID", team_id=1, team_short=team_short, price_tenths=50,
                           xp=1.0, median=1.0, floor=1.0, ceiling=1.0, confidence="n/a", expected_minutes=0.0)


def test_historical_clubs_become_distinct_team_ids_for_the_club_limit():
    out = _with_club_ids([_c(1, "LEI"), _c(2, "LEI"), _c(3, "ARS")])
    assert out[0].team_id == out[1].team_id != out[2].team_id
    assert all(c.team_id >= 10_000 for c in out)
