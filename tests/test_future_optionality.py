"""Regression tests for real future-optionality measurement (2026-09-02,
Phase 5B optimizer forensic rebuild, PART 2; semantics fixed Phase 5C PART 1)."""
from fpl_agent.optimization.future_optionality import (
    OptionalityAssessment,
    assess_future_optionality,
    compare_optionality,
)


def _seed_pool(conn, club_limit=3):
    now = "2026-01-01T00:00:00Z"
    conn.execute(f"INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Team A','TMA','{now}')")
    conn.execute(f"INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (2,2,'Team B','TMB','{now}')")
    conn.execute(
        f"INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, squad_min_play, "
        f"squad_max_play, squad_select, updated_at) VALUES (1,'Forward','FWD','Forwards',1,3,3,'{now}')"
    )
    # Owned player, price 50.
    conn.execute(f"INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (1,1,'Owned',1,1,'a',0,'{now}')")
    conn.execute(f"INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) VALUES (1, 50, '{now}', NULL)")
    # 3 real affordable replacements at various prices, 1 unaffordable, 1 premium.
    for pid, price in ((2, 40), (3, 55), (4, 60), (5, 200), (6, 95)):
        conn.execute(f"INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES ({pid},{pid},'P{pid}',2,1,'a',0,'{now}')")
        conn.execute(f"INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) VALUES ({pid}, {price}, '{now}', NULL)")
    conn.commit()


def test_counts_only_real_affordable_same_position_candidates(db_conn):
    _seed_pool(db_conn)
    # Bank = 10 -> budget = 50 + 10 = 60. Affordable: 40, 55, 60 (3 real).
    # Unaffordable: 200. Premium (>=90) and affordable: none at this bank.
    result = assess_future_optionality(db_conn, [1], bank_tenths=10)

    assert result.reachable_successor_count == 3
    assert result.per_player[1] == 3


def test_premium_access_counted_when_bank_allows_it(db_conn):
    _seed_pool(db_conn)
    # Budget = 50 + 200 = 250 -> everything affordable, including the real
    # 95-priced and 200-priced premium options.
    result = assess_future_optionality(db_conn, [1], bank_tenths=200)

    assert result.reachable_successor_count == 5
    assert result.premium_access_count == 2  # 95 and 200 are both >= 90


def test_zero_bank_still_counts_real_same_or_cheaper_replacements(db_conn):
    _seed_pool(db_conn)
    result = assess_future_optionality(db_conn, [1], bank_tenths=0)

    # Budget = 50 -> only the real 40-priced replacement is affordable.
    assert result.reachable_successor_count == 1


def test_free_transfers_carried_through_not_recomputed(db_conn):
    _seed_pool(db_conn)
    result = assess_future_optionality(db_conn, [1], bank_tenths=0, free_transfers=2)

    assert result.free_transfers == 2


class TestReachableCountInvariant:
    """PART 1 (2026-09-02, Phase 5C) - a real, absolute reachable-successor
    COUNT can never be negative, whatever real squad/bank state it's
    computed for. Locks this in directly, independent of any comparison
    logic."""

    def test_raw_count_is_never_negative_across_a_real_range_of_states(self, db_conn):
        _seed_pool(db_conn)
        for bank in (0, 5, 10, 50, 200, 10_000):
            result = assess_future_optionality(db_conn, [1], bank_tenths=bank)
            assert result.reachable_successor_count >= 0
            assert result.premium_access_count >= 0
            for v in result.per_player.values():
                assert v >= 0


class TestCompareOptionality:
    """PART 1 - `compare_optionality` is the ONE real place a signed delta
    is allowed to exist; every other quantity in `OptionalityAssessment`
    stays a plain, non-negative count."""

    def test_delta_is_a_real_signed_value_and_can_be_negative(self):
        baseline = OptionalityAssessment(bank_tenths=0, free_transfers=1, reachable_successor_count=2150, premium_access_count=3, per_player={})
        after = OptionalityAssessment(bank_tenths=23, free_transfers=5, reachable_successor_count=1740, premium_access_count=1, per_player={})

        comparison = compare_optionality(baseline, after)

        assert comparison.baseline_reachable_successors == 2150
        assert comparison.reachable_successors == 1740
        assert comparison.optionality_delta == -410
        assert comparison.premium_access_delta == -2

    def test_delta_can_also_be_positive(self):
        baseline = OptionalityAssessment(bank_tenths=0, free_transfers=1, reachable_successor_count=2150, premium_access_count=3, per_player={})
        after = OptionalityAssessment(bank_tenths=23, free_transfers=5, reachable_successor_count=2467, premium_access_count=3, per_player={})

        comparison = compare_optionality(baseline, after)

        assert comparison.optionality_delta == 317
        assert comparison.optionality_delta > 0

    def test_percent_change_is_computed_from_the_real_baseline(self):
        baseline = OptionalityAssessment(bank_tenths=0, free_transfers=1, reachable_successor_count=1000, premium_access_count=0, per_player={})
        after = OptionalityAssessment(bank_tenths=0, free_transfers=1, reachable_successor_count=900, premium_access_count=0, per_player={})

        comparison = compare_optionality(baseline, after)

        assert comparison.optionality_percent_change == -10.0

    def test_percent_change_is_none_not_a_fabricated_zero_when_baseline_is_zero(self):
        baseline = OptionalityAssessment(bank_tenths=0, free_transfers=1, reachable_successor_count=0, premium_access_count=0, per_player={})
        after = OptionalityAssessment(bank_tenths=0, free_transfers=1, reachable_successor_count=50, premium_access_count=0, per_player={})

        comparison = compare_optionality(baseline, after)

        assert comparison.optionality_percent_change is None
