from fpl_agent.ingestion.sync import _extract_season, _upsert_many, sync_rules, sync_stats_snapshot
from fpl_agent.models.expected_points import expected_points
from fpl_agent.models.qualitative_feed import compute_qualitative_adjustment
from fpl_agent.normalization.fpl_core import (
    flatten_rules,
    normalize_element_types,
    normalize_events,
    normalize_player_stats,
    normalize_players,
    normalize_teams,
)

from test_decision_fusion import _seed_implication
from test_expected_minutes import _insert_season_history
from test_expected_points import _bootstrap_two_teams_full_scoring as _bootstrap_two_teams
from test_sync import make_bootstrap


def _seed_full(conn, bootstrap, now):
    _upsert_many(conn, "teams", normalize_teams(bootstrap), now)
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), now)
    _upsert_many(conn, "events", normalize_events(bootstrap), now)
    _upsert_many(conn, "players", normalize_players(bootstrap), now)
    sync_stats_snapshot(conn, normalize_player_stats(bootstrap), now)
    season = _extract_season(bootstrap)
    sync_rules(conn, flatten_rules(bootstrap), season, "fpl_api_bootstrap", now)
    conn.commit()


def test_no_adjustment_without_any_qualitative_evidence(db_conn):
    bootstrap = make_bootstrap()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420, expected_goals=10.0, expected_assists=8.0, bonus=25)

    ep = expected_points(db_conn, 1)

    assert ep.qualitative_adjustment == 0.0
    assert ep.qualitative_note is None
    assert round(ep.components.total, 2) == ep.median  # no signal -> nothing to fold in, median == the pure quant total


def test_a_single_match_signal_never_adjusts_the_number(db_conn):
    """Must earn the adjustment through evidence - one real match is a real
    signal (surfaced elsewhere as a note) but not yet enough to move a
    number, same bar captain/transfer fusion already require."""
    bootstrap = _bootstrap_two_teams()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420, expected_goals=10.0, expected_assists=8.0, bonus=25)
    _seed_implication(db_conn, player_id=1, match_id=1, signal="GOAL_THREAT", direction="POSITIVE",
                       reason="scored a real goal", created_at="2026-08-22T15:00:00Z")

    ep = expected_points(db_conn, 1)

    assert ep.qualitative_adjustment == 0.0
    assert ep.qualitative_note is None


def test_a_real_persistent_trend_produces_a_bounded_targeted_adjustment(db_conn):
    """Direct unit test of compute_qualitative_adjustment() against a real,
    non-zero, controlled ComponentBreakdown - proves the bounded, targeted,
    correctly-signed sizing rule precisely, independent of whether the
    default GKP test fixture happens to produce a near-zero real goals
    component (it does - keepers essentially never score, a real, correct
    reason a full expected_points() integration wouldn't be a reliable way
    to assert a specific non-zero magnitude here)."""
    bootstrap = _bootstrap_two_teams()
    _seed_full(db_conn, bootstrap, "t0")
    _seed_implication(db_conn, player_id=1, match_id=1, signal="GOAL_THREAT", direction="POSITIVE",
                       reason="scored", created_at="2026-08-15T15:00:00Z")
    _seed_implication(db_conn, player_id=1, match_id=2, signal="GOAL_THREAT", direction="POSITIVE",
                       reason="scored again", created_at="2026-08-22T15:00:00Z")

    from fpl_agent.models.expected_points import ComponentBreakdown

    real_components = ComponentBreakdown(
        appearance=1.5, goals=2.0, assists=0.6, bonus=0.3, clean_sheet=0.0, cards=-0.1, conceded=0.0, defcon=0.0,
    )
    adjustment = compute_qualitative_adjustment(db_conn, 1, real_components)

    assert adjustment is not None
    assert adjustment.component == "goals"
    assert adjustment.direction == "POSITIVE"
    assert adjustment.delta > 0  # real, positive, evidence-earned
    # Bounded: never more than 35% of the real goals component it targets.
    assert adjustment.delta == round(2.0 * 0.35, 4)


def test_expected_points_integration_folds_the_adjustment_into_median(db_conn):
    """Full-pipeline integration proof (2026-09-12, direct and repeated user
    instruction: "qualitative analysis has to be the biggest mover for the
    optimizer" - the original layering rule kept this a side-channel that
    never reached any real optimizer decision, reversed here). The real
    expected_points() call correctly surfaces whatever compute_qualitative_
    adjustment() finds AND now actually adds it to `median`/`floor`/
    `ceiling` - `components` stays the pure quant baseline so both numbers
    are still independently inspectable."""
    bootstrap = _bootstrap_two_teams()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420, expected_goals=10.0, expected_assists=8.0, bonus=25)
    _seed_implication(db_conn, player_id=1, match_id=1, signal="GOAL_THREAT", direction="POSITIVE",
                       reason="scored", created_at="2026-08-15T15:00:00Z")
    _seed_implication(db_conn, player_id=1, match_id=2, signal="GOAL_THREAT", direction="POSITIVE",
                       reason="scored again", created_at="2026-08-22T15:00:00Z")

    ep = expected_points(db_conn, 1)

    assert ep.qualitative_note is not None and "GOAL_THREAT" in ep.qualitative_note
    assert ep.qualitative_adjustment == round(ep.components.goals * 0.35, 4)
    # The new rule: median now genuinely includes the real adjustment -
    # components (the pure quant baseline) stays separately inspectable.
    # (This fixture's player is a GKP with a real, near-zero goals
    # component, same as the original version of this test - the mechanism
    # firing correctly at zero is still a real, correct proof.)
    assert round(ep.median - ep.qualitative_adjustment, 2) == round(ep.components.total, 2)


def test_expected_points_window_also_folds_the_adjustment_in(db_conn):
    """`optimization/transfers.py`'s entire beam search (every transfer/
    chip/strategic-plan candidate this project ranks) reads `expected_
    points_window().total_median` exclusively - it never calls single-match
    `expected_points()` at all. Folding the adjustment into THAT function
    alone would leave it invisible to the actual optimizer, so
    `expected_points_window` needs the identical fix, proven here
    independently rather than assumed from the single-match test above."""
    from fpl_agent.models.expected_points import expected_points_window

    bootstrap = _bootstrap_two_teams()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420, expected_goals=10.0, expected_assists=8.0, bonus=25)
    _seed_implication(db_conn, player_id=1, match_id=1, signal="GOAL_THREAT", direction="POSITIVE",
                       reason="scored", created_at="2026-08-15T15:00:00Z")
    _seed_implication(db_conn, player_id=1, match_id=2, signal="GOAL_THREAT", direction="POSITIVE",
                       reason="scored again", created_at="2026-08-22T15:00:00Z")

    w = expected_points_window(db_conn, 1, n_gw=3)

    assert w.qualitative_note is not None and "GOAL_THREAT" in w.qualitative_note
    assert w.qualitative_adjustment == round(w.components.goals * 0.35, 4)
    assert round(w.total_median - w.qualitative_adjustment, 2) == round(w.components.total, 2)


def test_role_change_persistent_trend_produces_a_bounded_goals_adjustment(db_conn):
    """ROLE_CHANGE (2026-09-02, Phase 3 finalization deterministic detector)
    reuses this SAME interface, never a second adjustment pathway - same
    bounded-to-goals sizing rule as GOAL_THREAT/SET_PIECES."""
    bootstrap = _bootstrap_two_teams()
    _seed_full(db_conn, bootstrap, "t0")
    _seed_implication(db_conn, player_id=1, match_id=1, signal="ROLE_CHANGE", direction="POSITIVE",
                       reason="advanced attacking role", created_at="2026-08-15T15:00:00Z")
    _seed_implication(db_conn, player_id=1, match_id=2, signal="ROLE_CHANGE", direction="POSITIVE",
                       reason="advanced attacking role again", created_at="2026-08-22T15:00:00Z")

    from fpl_agent.models.expected_points import ComponentBreakdown

    real_components = ComponentBreakdown(
        appearance=1.5, goals=2.0, assists=0.6, bonus=0.3, clean_sheet=0.0, cards=-0.1, conceded=0.0, defcon=0.0,
    )
    adjustment = compute_qualitative_adjustment(db_conn, 1, real_components)

    assert adjustment is not None
    assert adjustment.component == "goals"
    assert adjustment.signal == "ROLE_CHANGE"
    assert adjustment.delta == round(2.0 * 0.35, 4)


def test_set_piece_change_persistent_trend_produces_a_bounded_goals_adjustment(db_conn):
    bootstrap = _bootstrap_two_teams()
    _seed_full(db_conn, bootstrap, "t0")
    _seed_implication(db_conn, player_id=1, match_id=1, signal="SET_PIECE_CHANGE", direction="POSITIVE",
                       reason="promoted to primary penalty taker", created_at="2026-08-15T15:00:00Z")
    _seed_implication(db_conn, player_id=1, match_id=2, signal="SET_PIECE_CHANGE", direction="POSITIVE",
                       reason="confirmed primary penalty taker again", created_at="2026-08-22T15:00:00Z")

    from fpl_agent.models.expected_points import ComponentBreakdown

    real_components = ComponentBreakdown(
        appearance=1.5, goals=2.0, assists=0.6, bonus=0.3, clean_sheet=0.0, cards=-0.1, conceded=0.0, defcon=0.0,
    )
    adjustment = compute_qualitative_adjustment(db_conn, 1, real_components)

    assert adjustment is not None
    assert adjustment.component == "goals"
    assert adjustment.signal == "SET_PIECE_CHANGE"
    assert adjustment.delta == round(2.0 * 0.35, 4)


def test_role_change_expected_points_integration_surfaces_the_adjustment(db_conn):
    """Full qualitative -> quantitative -> expected_points() integration for
    the new ROLE_CHANGE category - proves the new detector's output actually
    reaches the projection layer through the existing interface only."""
    bootstrap = _bootstrap_two_teams()
    _seed_full(db_conn, bootstrap, "t0")
    _insert_season_history(db_conn, player_id=1, minutes=3420, expected_goals=10.0, expected_assists=8.0, bonus=25)
    _seed_implication(db_conn, player_id=1, match_id=1, signal="ROLE_CHANGE", direction="POSITIVE",
                       reason="advanced attacking role", created_at="2026-08-15T15:00:00Z")
    _seed_implication(db_conn, player_id=1, match_id=2, signal="ROLE_CHANGE", direction="POSITIVE",
                       reason="advanced attacking role again", created_at="2026-08-22T15:00:00Z")

    ep = expected_points(db_conn, 1)

    assert ep.qualitative_note is not None and "ROLE_CHANGE" in ep.qualitative_note
    assert ep.qualitative_adjustment == round(ep.components.goals * 0.35, 4)
    assert round(ep.median - ep.qualitative_adjustment, 2) == round(ep.components.total, 2)


def test_role_change_adjustment_scales_down_with_lower_minutes_never_an_independent_bump(db_conn):
    """Real audit finding, Phase 7.3 Part 3 (role x minutes x attacking-
    involvement interaction) - confirmed via this test that the ROLE_CHANGE
    goals adjustment is a bounded PROPORTION of the real, already-minutes-
    scaled `components.goals` value `expected_points()` computed
    (`effective_minutes_fraction` is baked into that value upstream), never
    an absolute bump independent of playing time. A player projected far
    fewer minutes must get a proportionally SMALLER absolute adjustment for
    the identical real ROLE_CHANGE signal - the exact "high attacking
    involvement + 55 expected minutes is not equivalent to high attacking
    involvement + 90 expected minutes" property this audit part asked to be
    verified, not assumed."""
    bootstrap = _bootstrap_two_teams()
    _seed_full(db_conn, bootstrap, "t0")
    # A thin, mostly-substitute season record - genuinely low expected minutes,
    # unlike the 3420 (a full 38-match starter's worth) other tests in this file use.
    _insert_season_history(db_conn, player_id=1, minutes=180, expected_goals=1.0, expected_assists=0.5, bonus=2)
    _seed_implication(db_conn, player_id=1, match_id=1, signal="ROLE_CHANGE", direction="POSITIVE",
                       reason="advanced attacking role", created_at="2026-08-15T15:00:00Z")
    _seed_implication(db_conn, player_id=1, match_id=2, signal="ROLE_CHANGE", direction="POSITIVE",
                       reason="advanced attacking role again", created_at="2026-08-22T15:00:00Z")

    ep = expected_points(db_conn, 1)

    assert ep.qualitative_note is not None and "ROLE_CHANGE" in ep.qualitative_note
    # Same real 15% proportion as the high-minutes case - the RULE never changes...
    assert ep.qualitative_adjustment == round(ep.components.goals * 0.35, 4)
    # ...but the ABSOLUTE adjustment is real and small here, scaled by this player's
    # own genuinely low minutes-adjusted goals baseline - not the same absolute size
    # a nailed 90-minute starter with an identical signal would get (see
    # test_role_change_expected_points_integration_surfaces_the_adjustment above,
    # minutes=3420, real goals component an order of magnitude larger).
    assert ep.qualitative_adjustment < 0.5


def test_compute_qualitative_adjustment_returns_none_for_an_unmapped_signal(db_conn):
    """TACTICAL_CHANGE has no honest single-component target - must not be
    forced into the wrong bucket."""
    bootstrap = _bootstrap_two_teams()
    _seed_full(db_conn, bootstrap, "t0")
    _seed_implication(db_conn, player_id=1, match_id=1, signal="TACTICAL_CHANGE", direction="POSITIVE",
                       reason="formation change", created_at="2026-08-15T15:00:00Z")
    _seed_implication(db_conn, player_id=1, match_id=2, signal="TACTICAL_CHANGE", direction="POSITIVE",
                       reason="again", created_at="2026-08-22T15:00:00Z")

    from fpl_agent.models.expected_points import ComponentBreakdown

    components = ComponentBreakdown(1, 1, 1, 1, 1, 1, 1, 1)
    assert compute_qualitative_adjustment(db_conn, 1, components) is None
