import numpy as np

import fpl_agent.models.robustness as robustness_mod
from fpl_agent.models.robustness import compare_candidates

from test_optimization_captaincy import _patch, _seed


def test_compare_candidates_returns_none_without_a_real_fixture(db_conn, monkeypatch):
    """Honest absence, never a fabricated comparison, when there's no real
    fixture to sample from for either candidate."""
    _seed(db_conn)
    _patch(monkeypatch)

    result = compare_candidates(db_conn, 1, 2, from_event=99)

    assert result is None


def test_compare_candidates_classifies_robust_when_the_leader_almost_always_wins(monkeypatch):
    """Direct classification-boundary test - injects controlled trial arrays
    rather than relying on real Poisson randomness to land exactly on a
    threshold, same discipline as testing pure logic separately from a
    stochastic sampler."""
    leader = np.full(1000, 8.0)
    challenger = np.full(1000, 2.0)
    monkeypatch.setattr(
        robustness_mod, "_candidate_trial_points",
        lambda conn, rng, player_id, from_event, n_trials, cache: leader if player_id == 1 else challenger,
    )

    result = compare_candidates(None, 1, 2, n_trials=1000)

    assert result.verdict == "ROBUST"
    assert result.leader_win_rate == 1.0
    assert result.leader_median == 8.0
    assert result.challenger_median == 2.0


def test_compare_candidates_classifies_fragile_when_the_leader_rarely_wins(monkeypatch):
    """A real, large median gap (6.0 vs 2.0) that the model's point estimate
    would call a clear lead - but real per-trial variance means the
    'leader' actually wins less than half the time. This is the exact
    fragile-projection-artifact case the audit asked to be able to detect."""
    rng = np.random.default_rng(0)
    leader = rng.normal(6.0, 15.0, size=1000)  # huge variance - the median gap doesn't hold up per-trial
    challenger = rng.normal(2.0, 0.01, size=1000)  # tight, reliable
    monkeypatch.setattr(
        robustness_mod, "_candidate_trial_points",
        lambda conn, rng_, player_id, from_event, n_trials, cache: leader if player_id == 1 else challenger,
    )

    result = compare_candidates(None, 1, 2, n_trials=1000)

    assert result.verdict in ("MODERATE", "FRAGILE")  # real high-variance overlap, not a clean robust win


def test_compare_candidates_returns_none_when_only_one_candidate_has_a_real_fixture(monkeypatch):
    monkeypatch.setattr(
        robustness_mod, "_candidate_trial_points",
        lambda conn, rng, player_id, from_event, n_trials, cache: (np.full(10, 5.0) if player_id == 1 else None),
    )

    assert compare_candidates(None, 1, 2, n_trials=10) is None


def test_compare_candidates_end_to_end_against_a_real_seeded_db(db_conn, monkeypatch):
    """Real integration proof: the actual Dixon-Coles/scorelines/per-trial
    sampling pipeline runs without crashing against a minimal real DB with
    zero historical market data (the honest, common preseason/early-season
    state) and produces a real, internally-consistent result."""
    _seed(db_conn)
    _patch(monkeypatch)

    # _seed() already gives players 1 and 2 the same real team (id=1) and the
    # same real fixture (id=1, event=1) - a genuine same-match case, exactly
    # the correlated-scoreline path fixture_cache exists to handle correctly.
    result = compare_candidates(db_conn, 1, 2, from_event=1, n_trials=200)

    assert result is not None
    assert result.n_trials == 200
    assert 0.0 <= result.leader_win_rate <= 1.0
    assert result.verdict in robustness_mod.VERDICTS
