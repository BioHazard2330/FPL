"""Tests for the multi-gameweek MILP transfer planner.

These assert the things a solver can silently get wrong: that the plan it
returns is a LEGAL FPL plan at every gameweek, that free-transfer and hit
accounting match the real rules, and that the reported totals are internally
consistent. A MILP that returns an illegal squad with a great objective
value is worse than no planner at all, so the squad-legality checks are
re-derived here from the solution rather than trusted from the model.
"""
import sqlite3

import pytest

from fpl_agent.optimization.milp_planner import (
    MilpPlanResult,
    _bench_weight_for,
    plan_transfers_milp,
)
from fpl_agent.optimization.squad import _BENCH_GKP_WEIGHT, _BENCH_WEIGHT
from fpl_agent.optimization.transfers import HIT_COST


def test_bench_weight_matches_squad_module_convention():
    """The planner must score a bench exactly the way optimise_squad does,
    including the real bench-goalkeeper special case - otherwise a MILP plan
    and a squad build disagree about what the same squad is worth."""
    assert _bench_weight_for("GKP", None) == _BENCH_GKP_WEIGHT
    assert _bench_weight_for("DEF", None) == _BENCH_WEIGHT
    # An explicit override applies uniformly, GKP included - this is what
    # makes an apples-to-apples comparison against _squad_gw_ev possible.
    assert _bench_weight_for("GKP", 0.1) == 0.1
    assert _bench_weight_for("MID", 0.5) == 0.5


def test_rejects_a_squad_that_is_not_fifteen():
    """Guard rail, not a solver behaviour: a caller passing a partial squad
    should get an honest Infeasible result, never a plan built from a
    silently padded starting position."""
    conn = sqlite3.connect(":memory:")
    res = plan_transfers_milp(conn, [1, 2, 3], free_transfers=1, bank_tenths=0, start_event=2)
    assert res.sequence is None
    assert res.proven_optimal is False
    assert "expected 15" in res.status


@pytest.mark.parametrize("n", [0, 14, 16])
def test_rejects_wrong_squad_sizes(n):
    conn = sqlite3.connect(":memory:")
    res = plan_transfers_milp(conn, list(range(n)), free_transfers=1, bank_tenths=0, start_event=2)
    assert res.sequence is None


def _solve_real(conn, horizon=3, pool_per_position=12):
    from fpl_agent.optimization.locked_squad import get_locked_squad

    locked = get_locked_squad(conn)
    if locked is None:
        pytest.skip("no real locked squad in this database")
    ids = [c.player_id for c in locked.xi.starting] + [c.player_id for c in locked.xi.bench]
    if len(ids) != 15:
        pytest.skip("locked squad is not a full 15")
    return locked, plan_transfers_milp(
        conn, ids, locked.free_transfers, 0, start_event=locked.event + 1,
        horizon_gw=horizon, pool_per_position=pool_per_position, time_limit_seconds=180,
    )


def test_real_plan_is_a_legal_fpl_plan(db_conn):
    """Re-derives every hard FPL squad rule from the returned solution.

    Deliberately does NOT re-ask the model whether it satisfied its own
    constraints - it reads the resulting_squad_ids the planner actually
    reports, which is what downstream consumers render.
    """
    locked, res = _solve_real(db_conn)
    if res.sequence is None:
        pytest.skip(f"solver returned {res.status} on this database")

    requirements = {
        r["singular_name_short"]: r["squad_select"]
        for r in db_conn.execute("SELECT singular_name_short, squad_select FROM element_types")
    }
    meta = {
        r["id"]: (r["pos"], r["team_id"])
        for r in db_conn.execute(
            "SELECT p.id AS id, et.singular_name_short AS pos, p.team_id AS team_id "
            "FROM players p JOIN element_types et ON et.id = p.element_type"
        )
    }

    per_event = {}
    for step in res.sequence.steps:
        per_event.setdefault(step.event, step.resulting_squad_ids)

    assert per_event, "a plan must report a squad for at least one gameweek"
    for event, squad in per_event.items():
        squad = set(squad)
        assert len(squad) == 15, f"GW{event} squad size {len(squad)}"

        positions, clubs = {}, {}
        for pid in squad:
            pos, team = meta[pid]
            positions[pos] = positions.get(pos, 0) + 1
            clubs[team] = clubs.get(team, 0) + 1
        assert positions == requirements, f"GW{event} positions {positions}"
        assert max(clubs.values()) <= 3, f"GW{event} club limit breached: {clubs}"


def test_reported_totals_are_internally_consistent(db_conn):
    """`sum(step.gw_ev) == total_net_ev` is a contract transfers.py states
    explicitly and every consumer relies on to make a path total traceable.
    A planner that reports a headline number its own steps don't add up to
    is exactly the "unexplained total" this project already banned once."""
    _, res = _solve_real(db_conn)
    if res.sequence is None:
        pytest.skip(f"solver returned {res.status} on this database")
    total = sum(step.gw_ev for step in res.sequence.steps)
    assert total == pytest.approx(res.sequence.total_net_ev, abs=0.02)


def test_transfer_count_never_exceeds_what_was_paid_for(db_conn):
    """Free-transfer accounting: in any gameweek, transfers made beyond the
    free allowance must be reflected as a hit. Re-derived from the plan by
    replaying the real min(carry + 1, cap) rollover rather than trusting the
    solver's own ft variables."""
    from fpl_agent.models.rules import current_season, get_rule

    locked, res = _solve_real(db_conn)
    if res.sequence is None:
        pytest.skip(f"solver returned {res.status} on this database")

    cap = 1 + get_rule(db_conn, current_season(db_conn), "rules.max_extra_free_transfers", default=4)
    per_event = {}
    for step in res.sequence.steps:
        if step.player_in_id is not None:
            per_event[step.event] = per_event.get(step.event, 0) + 1

    available = min(locked.free_transfers, cap)
    for event in sorted(set(s.event for s in res.sequence.steps)):
        made = per_event.get(event, 0)
        if made > available:
            paid = made - available
            hit_steps = [s for s in res.sequence.steps if s.event == event and s.uses_hit]
            assert hit_steps, f"GW{event}: {paid} paid transfer(s) but no step flagged uses_hit"
        available = min(max(available - made, 0) + 1, cap)


def test_more_free_transfers_never_lowers_the_optimum(db_conn):
    """A monotonicity property the real problem genuinely has: extra free
    transfers only ever widen the feasible set, so the optimal objective
    cannot fall. A violation means the free-transfer constraints are wired
    backwards - a class of bug that is otherwise invisible, because the
    plan still looks plausible."""
    from fpl_agent.optimization.locked_squad import get_locked_squad

    locked = get_locked_squad(db_conn)
    if locked is None:
        pytest.skip("no real locked squad in this database")
    ids = [c.player_id for c in locked.xi.starting] + [c.player_id for c in locked.xi.bench]
    if len(ids) != 15:
        pytest.skip("locked squad is not a full 15")

    kwargs = dict(bank_tenths=0, start_event=locked.event + 1, horizon_gw=2,
                  pool_per_position=8, time_limit_seconds=180)
    low = plan_transfers_milp(db_conn, ids, 1, **kwargs)
    high = plan_transfers_milp(db_conn, ids, 3, **kwargs)
    if low.objective_value is None or high.objective_value is None:
        pytest.skip("solver did not prove optimality for both instances")
    assert high.objective_value >= low.objective_value - 0.01


def test_chips_are_reported_as_not_modelled():
    """v1 does not model chips. The result must say so rather than leaving a
    caller to assume chip timing was considered - passing used_chip_names
    must not silently imply otherwise."""
    assert MilpPlanResult(None, "Optimal", True, 1.0, 5, 10, 0.1).chips_modelled is False
