import pytest

from fpl_agent.ingestion.market_identity import get_or_create_market_team
from fpl_agent.models.promoted_team_calibration import (
    CalibrationShift,
    augment_model_with_promoted_teams,
    compute_calibration_shift,
    fit_secondary_division,
    invalidate_cache_for_connection,
    load_secondary_division_matches,
    seed_promoted_team_strength,
)
from fpl_agent.models.team_strength_dc import DixonColesModel, TeamStrength


def _seed_secondary_division(conn):
    conn.execute("INSERT INTO market_teams (id, canonical_name) VALUES (1, 'A'), (2, 'B'), (3, 'C')")
    rows = []
    for i in range(12):  # enough matches for a real DC fit to converge
        h, a = (1, 2) if i % 2 == 0 else (2, 1)
        rows.append(("E1", "2024-25", f"2024-09-{i+1:02d}", h, a, 2, 0, "test", "t0"))
        h2, a2 = (1, 3) if i % 2 == 0 else (3, 1)
        rows.append(("E1", "2024-25", f"2024-10-{i+1:02d}", h2, a2, 1, 1, "test", "t0"))
    conn.executemany(
        "INSERT INTO secondary_division_match_results "
        "(division, season, match_date, home_team_id, away_team_id, home_goals, away_goals, source, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()


def test_load_secondary_division_matches(db_conn):
    _seed_secondary_division(db_conn)
    matches, team_ids = load_secondary_division_matches(db_conn, "E1", "2024-25")
    assert len(matches) == 24
    assert team_ids == [1, 2, 3]
    assert all(m.days_since == 0 for m in matches)


def test_load_secondary_division_matches_filters_by_division_and_season(db_conn):
    _seed_secondary_division(db_conn)
    matches, team_ids = load_secondary_division_matches(db_conn, "E1", "2099-00")
    assert matches == []
    assert team_ids == []


def test_fit_secondary_division(db_conn):
    _seed_secondary_division(db_conn)
    model = fit_secondary_division(db_conn, "E1", "2024-25")
    assert set(model.teams) == {1, 2, 3}


def test_fit_secondary_division_is_cached_per_connection(db_conn):
    # Real perf fix, 2026-08-21 part 2: fit_secondary_division only depends on
    # (division, season) - a real Dixon-Coles numerical fit, expensive to redo.
    # Proves the second call returns the exact same (not just equal) model
    # object rather than refitting, and that invalidate_cache_for_connection
    # forces a real refit.
    _seed_secondary_division(db_conn)
    first = fit_secondary_division(db_conn, "E1", "2024-25")
    second = fit_secondary_division(db_conn, "E1", "2024-25")
    assert second is first  # identity, not just equality - proves no refit happened

    invalidate_cache_for_connection(db_conn)
    third = fit_secondary_division(db_conn, "E1", "2024-25")
    assert third is not first  # cache cleared - a genuine new fit object
    assert set(third.teams) == set(first.teams)  # same underlying data -> same result


def test_fit_secondary_division_caches_the_no_data_case_too(db_conn):
    # The ValueError path (no matches for this division/season) must also be
    # cached - otherwise the cache never applies to the honest "nothing to
    # calibrate with" branch augment_model_with_promoted_teams hits every
    # time there's no backfilled data yet.
    with pytest.raises(ValueError):
        fit_secondary_division(db_conn, "E1", "2099-00")
    with pytest.raises(ValueError):
        fit_secondary_division(db_conn, "E1", "2099-00")  # still raises - cached, not silently fixed


def _team(market_team_id, attack, defence):
    return TeamStrength(market_team_id=market_team_id, attack=attack, defence=defence)


def test_compute_calibration_shift_averages_across_the_sample():
    championship_model = DixonColesModel(
        teams={10: _team(10, 0.0, 0.0), 20: _team(20, 0.2, -0.1)},
        home_advantage=0.2, rho=-0.1, reference_team_id=20,
    )
    pl_model = DixonColesModel(
        teams={10: _team(10, -0.4, 0.3), 30: _team(30, 0.0, 0.0)},  # 20 absent from PL fit (not this sample)
        home_advantage=0.3, rho=-0.05, reference_team_id=30,
    )

    shift = compute_calibration_shift(pl_model, championship_model, promoted_team_market_ids=[10, 20])

    assert shift.sample_size == 1  # only team 10 present in both
    assert shift.attack_shift == -0.4 - 0.0
    assert shift.defence_shift == 0.3 - 0.0
    assert shift.sample_market_team_ids == (10,)


def test_compute_calibration_shift_raises_when_sample_is_empty():
    championship_model = DixonColesModel(teams={10: _team(10, 0.0, 0.0)}, home_advantage=0.2, rho=0.0, reference_team_id=10)
    pl_model = DixonColesModel(teams={30: _team(30, 0.0, 0.0)}, home_advantage=0.2, rho=0.0, reference_team_id=30)

    import pytest
    with pytest.raises(ValueError):
        compute_calibration_shift(pl_model, championship_model, promoted_team_market_ids=[10])


def test_seed_promoted_team_strength_translates_the_championship_rating():
    shift = CalibrationShift(attack_shift=0.5, defence_shift=-0.3, sample_size=3, sample_market_team_ids=(1, 2, 3))
    championship_model = DixonColesModel(teams={99: _team(99, 0.1, 0.2)}, home_advantage=0.2, rho=0.0, reference_team_id=99)
    pl_model = DixonColesModel(teams={1: _team(1, 0.0, 0.0)}, home_advantage=0.3, rho=-0.1, reference_team_id=1)

    seeded = seed_promoted_team_strength(pl_model, championship_model, shift, team_market_id=99)

    assert seeded.attack == 0.1 + 0.5
    assert seeded.defence == 0.2 + (-0.3)


def test_seed_promoted_team_strength_never_overrides_a_real_pl_fit():
    shift = CalibrationShift(attack_shift=0.5, defence_shift=-0.3, sample_size=3, sample_market_team_ids=(1, 2, 3))
    championship_model = DixonColesModel(teams={1: _team(1, 9.9, 9.9)}, home_advantage=0.2, rho=0.0, reference_team_id=1)
    pl_model = DixonColesModel(teams={1: _team(1, 0.0, 0.0)}, home_advantage=0.3, rho=-0.1, reference_team_id=1)

    seeded = seed_promoted_team_strength(pl_model, championship_model, shift, team_market_id=1)

    assert seeded is None  # team 1 already has a real PL fit - never overridden


def test_seed_promoted_team_strength_returns_none_without_championship_data():
    shift = CalibrationShift(attack_shift=0.5, defence_shift=-0.3, sample_size=3, sample_market_team_ids=(1, 2, 3))
    championship_model = DixonColesModel(teams={}, home_advantage=0.2, rho=0.0, reference_team_id=1)
    pl_model = DixonColesModel(teams={}, home_advantage=0.3, rho=-0.1, reference_team_id=1)

    seeded = seed_promoted_team_strength(pl_model, championship_model, shift, team_market_id=99)

    assert seeded is None  # never fabricated for a team with no real data either


def test_augment_returns_none_unchanged_when_dc_model_is_none(db_conn):
    assert augment_model_with_promoted_teams(db_conn, None, "2026-27") is None


def test_augment_returns_dc_model_unchanged_with_no_secondary_division_data(db_conn):
    dc_model = DixonColesModel(teams={1: _team(1, 0.1, -0.1)}, home_advantage=0.3, rho=-0.05, reference_team_id=1)
    result = augment_model_with_promoted_teams(db_conn, dc_model, "2026-27")
    assert result is dc_model  # same object - a strict no-op, not even a copy


def _seed_teams_and_market(conn):
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1, 1, 'Established', 'EST', 't0')")
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (2, 2, 'Promoted', 'PRO', 't0')")
    conn.commit()


def test_augment_end_to_end_seeds_the_promoted_team_and_leaves_the_real_fit_untouched(db_conn):
    _seed_teams_and_market(db_conn)
    established_id = get_or_create_market_team(db_conn, "fpl", "Established")
    promoted_id = get_or_create_market_team(db_conn, "fpl", "Promoted")
    other_id = get_or_create_market_team(db_conn, "football_data", "Some Other Club")

    # "Established" already has a real PL fit - this is what the live path passes in.
    dc_model = DixonColesModel(
        teams={established_id: _team(established_id, 0.4, -0.2)}, home_advantage=0.3, rho=-0.05, reference_team_id=established_id,
    )

    # Historical Championship season (2024-25): "Established" appears here too
    # (the team that was promoted last season and now has a real 2025-26 PL
    # fit) - this is the calibration sample. Enough matches for a real fit.
    rows = []
    for i in range(12):
        h, a = (established_id, other_id) if i % 2 == 0 else (other_id, established_id)
        rows.append(("E1", "2024-25", f"2024-09-{i+1:02d}", h, a, 2, 1, "test", "t0"))
    # Candidate Championship season (2025-26): "Promoted" (this season's real
    # promoted team, no PL history at all) appears here.
    for i in range(12):
        h, a = (promoted_id, other_id) if i % 2 == 0 else (other_id, promoted_id)
        rows.append(("E1", "2025-26", f"2025-09-{i+1:02d}", h, a, 1, 0, "test", "t0"))
    db_conn.executemany(
        "INSERT INTO secondary_division_match_results "
        "(division, season, match_date, home_team_id, away_team_id, home_goals, away_goals, source, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    db_conn.commit()

    result = augment_model_with_promoted_teams(db_conn, dc_model, "2026-27")

    assert established_id in result.teams
    assert result.teams[established_id] == dc_model.teams[established_id]  # untouched - byte-identical
    assert promoted_id in result.teams  # the real gap this closes
    assert result.home_advantage == dc_model.home_advantage
    assert result.rho == dc_model.rho
