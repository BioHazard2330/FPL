"""The XI-aware transfer valuation, pinned against the production failure
that motivated it.

`evaluate_transfer` scores a swap as `ev_in - ev_out` - the raw difference
between two players' projections - which silently assumes every point the
incoming player scores reaches your total. For a swap involving the bench
that is false. In production it recommended selling squad slot 15 (the
deepest bench player, multiplier 0) in two consecutive gameweeks, valued
GW3's swap at +8.73, and realised exactly 0 against doing nothing.

`_with_xi_aware_value` rescores a candidate by what it does to the squad's
own starting-XI-aware EV. These tests use a stubbed `_squad_gw_ev` so they
assert the mechanism rather than any particular projection.
"""
from types import SimpleNamespace

import fpl_agent.optimization.transfers as transfers_mod
from fpl_agent.optimization.transfers import HIT_COST, TransferCandidate, _with_xi_aware_value


def _candidate(out_id, in_id, raw_net_3gw, uses_hit=False):
    return TransferCandidate(
        player_out_id=out_id, player_out_name=f"P{out_id}",
        player_in_id=in_id, player_in_name=f"P{in_id}",
        price_delta_tenths=0,
        ev_1gw=raw_net_3gw / 3, ev_3gw=raw_net_3gw, ev_5gw=raw_net_3gw * 5 / 3,
        net_ev_1gw=raw_net_3gw / 3, net_ev_3gw=raw_net_3gw, net_ev_5gw=raw_net_3gw * 5 / 3,
        uses_hit=uses_hit,
    )


def test_bench_to_bench_swap_collapses_to_zero(monkeypatch):
    """The production case. Both players sit on the bench, so the squad's
    XI-aware EV is identical before and after - regardless of how large the
    raw player-vs-player delta is."""
    squad = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
    # Squad EV does not depend on whether 15 or 99 is the 15th man.
    monkeypatch.setattr(transfers_mod, "_squad_gw_ev", lambda conn, ids, event, cache: 50.0)

    raw = _candidate(15, 99, raw_net_3gw=8.73)
    scored = _with_xi_aware_value(None, raw, squad, from_event=3, n_gw=3, cache={})

    assert scored.net_ev_3gw == 8.73, "raw delta is preserved for disclosure"
    assert scored.xi_aware_net_ev_3gw == 0.0, "but the XI-aware value is nothing"


def test_swap_that_upgrades_a_starter_keeps_its_value(monkeypatch):
    """The opposite case must not be flattened: replacing a starter with a
    better starter genuinely raises the squad's EV every gameweek."""
    squad = list(range(1, 16))

    def squad_ev(conn, ids, event, cache):
        return 53.0 if 99 in ids else 50.0  # +3 per gameweek with the new starter

    monkeypatch.setattr(transfers_mod, "_squad_gw_ev", squad_ev)
    raw = _candidate(1, 99, raw_net_3gw=9.0)
    scored = _with_xi_aware_value(None, raw, squad, from_event=3, n_gw=3, cache={})
    assert scored.xi_aware_ev_3gw == 9.0
    assert scored.xi_aware_net_ev_3gw == 9.0


def test_hit_cost_is_charged_against_the_xi_aware_value(monkeypatch):
    squad = list(range(1, 16))
    monkeypatch.setattr(
        transfers_mod, "_squad_gw_ev", lambda conn, ids, event, cache: 52.0 if 99 in ids else 50.0
    )
    raw = _candidate(1, 99, raw_net_3gw=6.0 - HIT_COST, uses_hit=True)
    scored = _with_xi_aware_value(None, raw, squad, from_event=3, n_gw=3, cache={})
    assert scored.xi_aware_ev_3gw == 6.0
    assert scored.xi_aware_net_ev_3gw == 6.0 - HIT_COST


def test_failure_leaves_the_candidate_untouched_rather_than_inventing_a_number(monkeypatch):
    """A wrong XI-aware value would silently re-introduce the bug this
    exists to fix. The honest failure is None, so a caller falls back to
    the raw delta it already had."""
    squad = list(range(1, 16))

    def boom(conn, ids, event, cache):
        raise RuntimeError("projection unavailable")

    monkeypatch.setattr(transfers_mod, "_squad_gw_ev", boom)
    raw = _candidate(1, 99, raw_net_3gw=5.0)
    scored = _with_xi_aware_value(None, raw, squad, from_event=3, n_gw=3, cache={})
    assert scored is raw
    assert scored.xi_aware_net_ev_3gw is None


def test_decision_layer_prefers_the_xi_aware_value_and_falls_back_to_raw():
    from fpl_agent.optimization.decision_analysis import _decision_value

    with_xi = SimpleNamespace(net_ev_3gw=8.73, xi_aware_net_ev_3gw=0.0)
    assert _decision_value(with_xi) == 0.0, "must not fall through to the raw delta when XI-aware is 0"

    without = SimpleNamespace(net_ev_3gw=8.73, xi_aware_net_ev_3gw=None)
    assert _decision_value(without) == 8.73
