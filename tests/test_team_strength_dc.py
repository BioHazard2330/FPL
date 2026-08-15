from fpl_agent.models.team_strength_dc import Match, expected_goals, fit_dixon_coles


def test_fit_dixon_coles_ranks_dominant_team_higher():
    # Team 1 beats team 2 heavily and repeatedly; team 3 is a mid-table draw-machine.
    matches = [
        Match(home_team_id=1, away_team_id=2, home_goals=3, away_goals=0, days_since=10),
        Match(home_team_id=2, away_team_id=1, home_goals=0, away_goals=3, days_since=20),
        Match(home_team_id=1, away_team_id=3, home_goals=2, away_goals=1, days_since=30),
        Match(home_team_id=3, away_team_id=1, home_goals=1, away_goals=2, days_since=40),
        Match(home_team_id=2, away_team_id=3, home_goals=1, away_goals=1, days_since=50),
        Match(home_team_id=3, away_team_id=2, home_goals=1, away_goals=1, days_since=60),
    ]
    model = fit_dixon_coles(matches, team_ids=[1, 2, 3], half_life_days=365.0)

    assert model.teams[1].attack > model.teams[2].attack
    assert model.teams[1].defence < model.teams[2].defence  # lower defence param = concedes less

    lam, mu = expected_goals(model, home_team_id=1, away_team_id=2)
    assert lam > mu  # team 1 expected to outscore team 2 even accounting for home/away


def test_fit_dixon_coles_requires_matches_and_teams():
    import pytest
    with pytest.raises(ValueError):
        fit_dixon_coles([], team_ids=[1, 2])
    with pytest.raises(ValueError):
        fit_dixon_coles([Match(1, 2, 1, 0, 0)], team_ids=[1])
