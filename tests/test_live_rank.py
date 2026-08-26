import pytest

from fpl_agent.models.live_rank import LiveRankEstimate, estimate_live_rank, estimate_squad_live_points


def test_estimate_squad_live_points_sums_multiplier_weighted_total_points():
    picks = [(1, 2), (2, 1), (3, 0)]  # captain (2x), a starter, an unused bench player
    live_payload = {"elements": [
        {"id": 1, "stats": {"total_points": 6}},
        {"id": 2, "stats": {"total_points": 2}},
        {"id": 3, "stats": {"total_points": 10}},  # bench, multiplier 0 - must not count
    ]}

    total = estimate_squad_live_points(picks, live_payload)

    assert total == 6 * 2 + 2 * 1  # 14 - player 3's 10 points never counted


def test_estimate_squad_live_points_missing_element_contributes_zero_not_a_crash():
    picks = [(1, 1), (99, 1)]  # 99 never appears in the live payload
    live_payload = {"elements": [{"id": 1, "stats": {"total_points": 4}}]}

    assert estimate_squad_live_points(picks, live_payload) == 4


def test_estimate_squad_live_points_empty_payload_returns_zero():
    assert estimate_squad_live_points([(1, 1)], {}) == 0


def test_estimate_live_rank_interpolates_between_two_real_bracketing_managers():
    # Rank 100 has 60 points, rank 200 has 50 points - a manager between them
    # linearly interpolates.
    reference = [(100, 60.0), (200, 50.0)]

    estimate = estimate_live_rank(reference, my_current_total=55.0, total_players=1_000_000)

    assert estimate.bracketed is True
    assert estimate.rank_lower_bound == 100
    assert estimate.rank_upper_bound == 200
    assert estimate.estimated_rank == 150  # exact midpoint, halfway between 60 and 50
    assert estimate.sample_size == 2


def test_estimate_live_rank_above_the_whole_sample_reports_a_wide_honest_bound():
    reference = [(100, 60.0), (200, 50.0)]

    estimate = estimate_live_rank(reference, my_current_total=100.0, total_players=1_000_000)

    assert estimate.bracketed is False
    assert estimate.rank_lower_bound == 1
    assert estimate.rank_upper_bound == 100  # can't be worse than the best sampled manager's own rank


def test_estimate_live_rank_below_the_whole_sample_reports_a_wide_honest_bound():
    reference = [(100, 60.0), (200, 50.0)]

    estimate = estimate_live_rank(reference, my_current_total=10.0, total_players=1_000_000)

    assert estimate.bracketed is False
    assert estimate.rank_lower_bound == 200  # can't be better than the worst sampled manager's own rank
    assert estimate.rank_upper_bound == 1_000_000


def test_estimate_live_rank_exact_match_at_a_sample_point():
    reference = [(100, 60.0), (200, 50.0), (300, 40.0)]

    estimate = estimate_live_rank(reference, my_current_total=50.0, total_players=1_000_000)

    assert estimate.bracketed is True
    assert estimate.estimated_rank == 200


def test_estimate_live_rank_raises_on_empty_reference():
    with pytest.raises(ValueError):
        estimate_live_rank([], my_current_total=50.0, total_players=1_000_000)


# --- PCHIP monotonic interpolation (2026-08-21, direct user request) -----


def test_estimate_live_rank_stays_monotonic_across_a_dense_real_looking_sample():
    """The actual property that matters: scanning a fine grid of possible
    scores across the sampled range, a higher score must never yield a
    numerically WORSE (higher) estimated rank than a lower score - the
    real "wobble" failure mode a naive cubic spline can produce between
    two anchor points, and the whole reason PCHIP was requested over plain
    linear/cubic interpolation."""
    # A real-looking, deliberately noisy sample: pre_gw_rank isn't a
    # perfect proxy for the post-live ordering (see module docstring) - a
    # few ranks are "out of order" relative to their own score neighbors.
    reference = [
        (50, 120.0), (400, 115.0), (300, 110.0), (900, 100.0),
        (700, 95.0), (2000, 80.0), (1500, 75.0), (5000, 50.0),
    ]
    estimates = [
        estimate_live_rank(reference, my_current_total=score, total_players=1_000_000).estimated_rank
        for score in range(52, 118)
    ]
    # As score strictly increases (list is built ascending), rank must
    # never strictly increase.
    for worse_score_rank, better_score_rank in zip(estimates, estimates[1:]):
        assert better_score_rank <= worse_score_rank


def test_enforce_monotonic_ranks_corrects_real_sample_noise():
    from fpl_agent.models.live_rank import _enforce_monotonic_ranks

    # Descending by score: rank 300 appearing after (lower score than) rank
    # 400 is the exact "swapped order" noise the module docstring
    # describes - a manager who started worse (400) but has a HIGHER score
    # here than one who started better (300) at this point in the sample.
    scores_desc = [120.0, 115.0, 110.0]
    ranks_desc = [50, 400, 300]  # 300 < 400 - a real violation at index 2

    corrected = _enforce_monotonic_ranks(scores_desc, ranks_desc)

    assert corrected == [50, 400, 400]  # clipped up to the running max, never down
    assert corrected == sorted(corrected)  # genuinely monotonic non-decreasing now


def test_estimate_live_rank_handles_exact_score_ties_without_crashing():
    """Two different real sampled managers landing on the exact same
    integer live total is a real, expected case (live points are whole
    numbers) - PchipInterpolator requires a strictly increasing x-axis, so
    ties must be collapsed before fitting, not crash the estimate."""
    reference = [(100, 60.0), (150, 60.0), (300, 40.0)]  # two managers tied at 60.0

    estimate = estimate_live_rank(reference, my_current_total=50.0, total_players=1_000_000)

    assert estimate.bracketed is True
    assert estimate.sample_size == 3  # real sample size reported, even though two ties collapsed to one anchor


def test_estimate_live_rank_exact_at_sample_point_matches_that_anchor_exactly():
    """PCHIP's own interpolation property: evaluated exactly AT a real
    anchor's x-value, the spline must return that anchor's own y-value,
    not a nearby-but-off number."""
    reference = [(100, 60.0), (200, 50.0), (300, 40.0), (500, 20.0)]

    estimate = estimate_live_rank(reference, my_current_total=40.0, total_players=1_000_000)

    assert estimate.estimated_rank == 300


def test_estimate_live_rank_flags_approximate_when_ranks_are_mostly_page_level(monkeypatch):
    """Real regression guard for a real bug found live (2026-08-27, direct
    user report "live rank is fucked"): a real fetched FPL standings page
    returned the IDENTICAL rank for every one of 50 distinct real entries -
    a genuine external API granularity limit, not this project's bug. A
    sample dominated by that kind of duplication must be flagged, not
    presented as a falsely-precise number."""
    # 20 distinct real entries, but only 2 truly distinct rank VALUES shared
    # across all of them (a real page-level-granularity shape) - well below
    # the 50%-distinct bar.
    reference = [(100, 60.0 - i * 0.01) for i in range(10)] + [(500, 40.0 - i * 0.01) for i in range(10)]

    estimate = estimate_live_rank(reference, my_current_total=50.0, total_players=1_000_000)

    assert estimate.precision == "approximate"


def test_estimate_live_rank_stays_precise_when_ranks_are_genuinely_distinct():
    reference = [(100, 60.0), (150, 58.0), (200, 55.0), (250, 52.0), (300, 50.0), (350, 48.0)]

    estimate = estimate_live_rank(reference, my_current_total=51.0, total_players=1_000_000)

    assert estimate.precision == "precise"
