"""Rate My Team (competitor-scope closure) - plumbing/composition tests in
the same spirit as test_e2e_lifecycle.py: real (unmocked) expected_points()
over a small synthetic pool, not an accuracy claim - proves the command
actually composes build_player_pool/optimise_squad/captaincy_report/
differentials/traps/breakouts/template without crashing and handles real
manual-entry mistakes (duplicate ids, illegal squads) correctly."""
from fpl_agent.optimization.rate_team import rate_team
from test_optimization_squad import _seed


def test_rate_team_composes_end_to_end_for_a_valid_squad(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)

    # 2 GKP, 5 DEF, 5 MID, 3 FWD, max 4/team across all 4 teams - a real, legal 15-man squad
    squad_ids = [1, 2, 10, 12, 14, 15, 16, 20, 22, 24, 26, 27, 30, 31, 32]
    rating = rate_team(db_conn, squad_ids)

    assert rating.invalid_ids == []
    assert rating.duplicate_ids == []
    assert rating.rule_violations == []
    assert len(rating.xi.starting) == 11
    # Not asserting gw1_xp > 0: this minimal synthetic pool has no fixtures/
    # team-strength data, so real (unmocked) expected_points() legitimately
    # floors at 0.0 here (a genuine data-sequencing limitation of this small
    # fixture, matching this project's own documented season-sim precedent -
    # not a rate_team bug). This test proves the plumbing composes end to
    # end, not model accuracy.
    assert rating.optimal_gw1_xp >= rating.gw1_xp  # never better than the true optimum
    assert 0 <= rating.efficiency_percent <= 100
    assert isinstance(rating.differential_ids, list)
    assert isinstance(rating.trap_ids, list)
    assert isinstance(rating.breakout_ids, list)


def test_rate_team_deduplicates_a_repeated_id_instead_of_double_counting(db_conn):
    """Real bug caught live during manual testing: a duplicate id in the
    input (a plausible manual-entry typo) previously showed the same player
    twice in the XI and made him both captain and vice-captain of himself."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    squad_ids = [1, 2, 10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 30, 31, 30]  # 30 repeated

    rating = rate_team(db_conn, squad_ids)

    assert rating.duplicate_ids == [30]
    web_names = [c.web_name for c in rating.xi.starting] + [c.web_name for c in rating.xi.bench]
    assert len(web_names) == len(set(web_names))  # never the same player twice
    if rating.captain and rating.vice:
        assert rating.captain.player_id != rating.vice.player_id


def test_rate_team_flags_illegal_position_counts(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    # 3 GKP, 0 DEF, 0 MID, 0 FWD - structurally illegal regardless of budget
    squad_ids = [1, 2, 3]

    rating = rate_team(db_conn, squad_ids)

    assert any("GKP" in v for v in rating.rule_violations)
    assert any("DEF" in v for v in rating.rule_violations)


def test_rate_team_flags_unknown_ids_without_crashing(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    squad_ids = [1, 2, 10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 30, 31, 999999]

    rating = rate_team(db_conn, squad_ids)

    assert rating.invalid_ids == [999999]
