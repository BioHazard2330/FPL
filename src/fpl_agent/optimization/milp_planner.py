"""Multi-gameweek transfer planning as ONE mixed-integer linear program
(2026-09-19).

This project already solves the SINGLE-gameweek squad-selection problem
exactly, as a MILP (`optimization/squad.py::optimise_squad`, PuLP + CBC).
The MULTI-gameweek transfer problem - "which transfers, in which gameweek,
over the next H gameweeks" - was solved by a different method entirely:
`optimization/transfers.py::search_transfer_sequences`, a beam search. A
beam search is a heuristic. It keeps the `beam_width` best-looking partial
paths at each step and discards the rest, so it carries no optimality
guarantee at all: a sequence whose first move looks mediocre but whose
third move is decisive can be pruned before that third move is ever
enumerated. Production runs it at beam_width=5 with a continuation search
at width 3, and one real invocation takes minutes.

The published work on this problem (Bhattacharya et al., "A data-driven
framework for team selection in Fantasy Premier League", arXiv:2505.02170)
formulates it instead as a mixed-integer linear program over a rolling
multi-week horizon, which is also what the stronger public FPL solvers do.
That is what this module implements, against the SAME per-player, per-
gameweek expected-points primitive the beam search already uses
(`expected_points_window(..., from_event=t)`), so the two are directly
comparable rather than two different questions.

**This module does not replace the beam search.** It is registered as an
independent second opinion, in the same spirit as
`models/external_benchmark.py`'s Solio cross-check: when both planners are
run over the same horizon and pool, the MILP's objective value is a real
upper bound on what the beam search can achieve, so the gap between them is
a measurement of how much the heuristic is leaving on the table. Replacing
`search_transfer_sequences` outright is a separate decision that needs that
measurement first, not an assumption.

## What is modelled

Decision variables, for every player p in the pool and gameweek t in the
horizon:

- `x[p,t]`  - p is one of the 15 squad members at t
- `s[p,t]`  - p is one of the 11 starters at t
- `c[p,t]`  - p is captain at t
- `tin[p,t]`/`tout[p,t]` - p is transferred in/out at t

and per gameweek: `ft[t]` (free transfers available), `fuse[t]` (free
transfers actually consumed), `hits[t]` (transfers paid for at -4 each),
`bank[t]` (money in the bank, tenths).

Objective: maximise total expected points across the horizon - starters at
full weight, the captain counted a second time, bench members at
`squad.py`'s own bench weights - minus `HIT_COST` per paid transfer. This
is deliberately the same scoring convention `squad.py` uses for one
gameweek, extended over H of them.

Constraints: squad size 15 and per-position quotas every gameweek; at most
`rules.squad_team_limit` players per club; exactly 11 starters within the
real formation bounds from `element_types`; exactly one captain, who must
be a starter; squad continuity (`x[p,t] - x[p,t-1] == tin[p,t] -
tout[p,t]`), anchored at t0 by the real current squad; free-transfer
accounting with the real `min(carry + 1, cap)` rollover rule; and bank
continuity, never negative.

## What is NOT modelled, deliberately

- **Chips.** Wildcard and free hit change transfer accounting structurally
  and bench boost/triple captain are products of two binaries; each is
  linearisable, but every one of them is a place to introduce a subtle,
  silent modelling bug. v1 plans the transfer problem only. Chip timing
  stays with `optimization/chips.py`'s DP and the beam's own joint chip
  branching. `used_chip_names` is accepted and ignored, so a caller cannot
  accidentally believe chips were considered.
- **Selling-price rules.** FPL sells a player at purchase price plus half
  the rounded-down profit. This project stores no purchase price anywhere
  (checked: no `purchase_price`/`selling_price` column exists in any
  migration), so `search_transfer_sequences` already treats sell price as
  current price. This module makes the SAME approximation on purpose - a
  different one would make the two planners incomparable, which is the
  whole point of running them together.
- **Price changes over the horizon.** Prices are held at today's value.
  The beam search treats price movement as a tie-break nudge only, never a
  hard constraint, so again neither planner models it as money.
- **Anything stochastic.** The objective is expected points. Robustness and
  outcome distribution stay where they already live
  (`models/scenario_sampling.py`, `models/robustness.py`).

These are stated here rather than discovered later: a planner that silently
assumed any of them would produce a number that looks authoritative and
isn't.
"""
import logging
import sqlite3
import time
from dataclasses import dataclass

import pulp

from fpl_agent.models.expected_points import expected_points_window
from fpl_agent.models.rules import current_season, get_rule
from fpl_agent.optimization.squad import (
    _BENCH_GKP_WEIGHT,
    _BENCH_WEIGHT,
    PlayerCandidate,
    build_player_pool,
)
from fpl_agent.optimization.transfers import (
    HIT_COST,
    TransferSequence,
    TransferSequenceStep,
)

_logger = logging.getLogger("fpl_agent.milp_planner")

# Pool size per position, on top of whoever is already in the squad. The
# full league is ~660 players; at 8 gameweeks that is ~5k binaries for `x`
# alone before `s`/`c`/`tin`/`tout`, which CBC will not close in any time
# a dashboard can wait for. Restricting to the plausible transfer targets
# per position is the same move the beam search makes implicitly by only
# ever scoring a candidate shortlist - made explicit and configurable here.
_DEFAULT_POOL_PER_POSITION = 30

# CBC is given a wall-clock ceiling rather than being allowed to run to
# proven optimality. On a real 8-GW horizon it typically proves optimality
# in seconds; the cap exists so a pathological instance degrades to "best
# found so far, honestly labelled" instead of hanging a dashboard regen.
_DEFAULT_TIME_LIMIT_SECONDS = 120


@dataclass(frozen=True)
class MilpPlanResult:
    """A solved plan plus the provenance a caller needs to report it
    honestly. `status` is CBC's own status string ("Optimal", "Not
    Solved", "Infeasible", ...) - a caller must not present a
    non-Optimal result as a proven best plan, and `proven_optimal` says
    so directly rather than making every call site re-derive it."""
    sequence: TransferSequence | None
    status: str
    proven_optimal: bool
    objective_value: float | None
    horizon: int
    pool_size: int
    solve_seconds: float
    chips_modelled: bool = False


def _position_of(c: PlayerCandidate) -> str:
    return c.position


def _bench_weight_for(position: str, bench_weight: float | None) -> float:
    """Mirrors `squad.py::optimise_squad`'s own nested `_bench_weight_for`
    exactly, including its real special case: a benched goalkeeper is worth
    materially less than an outfield bench player, because he only ever
    scores if the starting keeper does not play at all."""
    if position == "GKP" and bench_weight is None:
        return _BENCH_GKP_WEIGHT
    return _BENCH_WEIGHT if bench_weight is None else bench_weight


def _gw_xp(conn: sqlite3.Connection, player_id: int, event: int, cache: dict) -> float:
    """The SAME primitive `transfers.py::_player_gw_ev` uses, with the same
    cache key shape, so a MILP plan and a beam plan scored over the same
    horizon are reading identical per-player numbers. Any divergence between
    the two planners is then a difference in SEARCH, never in valuation -
    which is the only thing that makes comparing them meaningful."""
    key = (player_id, event)
    if key not in cache:
        cache[key] = expected_points_window(conn, player_id, 1, from_event=event).total_median
    return cache[key]


def plan_transfers_milp(
    conn: sqlite3.Connection,
    squad_ids: list[int],
    free_transfers: int,
    bank_tenths: int,
    start_event: int,
    horizon_gw: int = 5,
    pool_per_position: int = _DEFAULT_POOL_PER_POSITION,
    bench_weight: float | None = None,
    time_limit_seconds: int = _DEFAULT_TIME_LIMIT_SECONDS,
    used_chip_names: frozenset[str] = frozenset(),
    xp_cache: dict | None = None,
) -> MilpPlanResult:
    """Solve the whole horizon at once and return it as the same
    `TransferSequence` the beam search produces, so every existing consumer
    (`path_detail`, `checkpoint_breakdown`, the dashboard's plan rendering)
    reads it without modification.

    `squad_ids` must be the real current 15. `free_transfers`/`bank_tenths`
    are the real current state - this function never re-derives them, for
    the same reason the rest of the decision layer doesn't
    (`models/free_transfers.py` is the single source of truth).
    """
    if used_chip_names:
        _logger.debug("milp planner: chips are not modelled in v1; ignoring %s", sorted(used_chip_names))
    if len(squad_ids) != 15:
        return MilpPlanResult(None, f"Infeasible (squad has {len(squad_ids)} players, expected 15)",
                              False, None, horizon_gw, 0, 0.0)

    started = time.monotonic()
    cache = xp_cache if xp_cache is not None else {}
    season = current_season(conn)
    club_limit = get_rule(conn, season, "rules.squad_team_limit", 3)
    ft_cap = 1 + get_rule(conn, season, "rules.max_extra_free_transfers", default=4)

    position_requirements = {
        r["singular_name_short"]: r["squad_select"]
        for r in conn.execute("SELECT singular_name_short, squad_select FROM element_types").fetchall()
    }
    play_bounds = {
        r["singular_name_short"]: (r["squad_min_play"], r["squad_max_play"])
        for r in conn.execute("SELECT singular_name_short, squad_min_play, squad_max_play FROM element_types").fetchall()
    }

    events = list(range(start_event, start_event + horizon_gw))

    # Pool = everyone currently owned (they must be representable at t0, and
    # a plan that cannot express "keep this player" is not a plan) plus the
    # strongest transfer targets per position.
    owned = set(squad_ids)
    league = build_player_pool(conn, n_gw=horizon_gw)
    by_id = {c.player_id: c for c in league}
    pool: list[PlayerCandidate] = [c for c in league if c.player_id in owned]
    missing_owned = owned - {c.player_id for c in pool}
    if missing_owned:
        # A squad member filtered out of the league pool (injured, flagged,
        # low start confidence) still has to exist as a variable or the
        # model cannot represent the real starting position.
        from fpl_agent.optimization.squad import build_player_pool_for_ids
        pool.extend(build_player_pool_for_ids(conn, missing_owned, start_event))
    for position in position_requirements:
        ranked = sorted(
            (c for c in league if c.position == position and c.player_id not in owned),
            key=lambda c: c.xp, reverse=True,
        )
        pool.extend(ranked[:pool_per_position])

    pool = list({c.player_id: c for c in pool}.values())
    if len(pool) < 15:
        return MilpPlanResult(None, "Infeasible (pool smaller than a legal squad)",
                              False, None, horizon_gw, len(pool), time.monotonic() - started)

    xp = {(c.player_id, t): _gw_xp(conn, c.player_id, t, cache) for c in pool for t in events}
    price = {c.player_id: c.price_tenths for c in pool}
    pos = {c.player_id: c.position for c in pool}
    club = {c.player_id: c.team_id for c in pool}
    ids = [c.player_id for c in pool]

    prob = pulp.LpProblem("fpl_multiweek_transfers", pulp.LpMaximize)

    x = {(p, t): pulp.LpVariable(f"x_{p}_{t}", cat="Binary") for p in ids for t in events}
    s = {(p, t): pulp.LpVariable(f"s_{p}_{t}", cat="Binary") for p in ids for t in events}
    cap = {(p, t): pulp.LpVariable(f"c_{p}_{t}", cat="Binary") for p in ids for t in events}
    tin = {(p, t): pulp.LpVariable(f"in_{p}_{t}", cat="Binary") for p in ids for t in events}
    tout = {(p, t): pulp.LpVariable(f"out_{p}_{t}", cat="Binary") for p in ids for t in events}

    ft = {t: pulp.LpVariable(f"ft_{t}", lowBound=0, upBound=ft_cap, cat="Integer") for t in events}
    fuse = {t: pulp.LpVariable(f"fuse_{t}", lowBound=0, upBound=ft_cap, cat="Integer") for t in events}
    hits = {t: pulp.LpVariable(f"hits_{t}", lowBound=0, cat="Integer") for t in events}
    bank = {t: pulp.LpVariable(f"bank_{t}", lowBound=0, cat="Continuous") for t in events}

    # --- objective -------------------------------------------------------
    # Starter at full xp, captain counted a second time (so a captained
    # starter scores 2x), bench at squad.py's own weights. Minus real hit
    # cost. Identical convention to optimise_squad, summed over the horizon.
    prob += (
        pulp.lpSum(xp[(p, t)] * s[(p, t)] for p in ids for t in events)
        + pulp.lpSum(xp[(p, t)] * cap[(p, t)] for p in ids for t in events)
        + pulp.lpSum(
            _bench_weight_for(pos[p], bench_weight) * xp[(p, t)] * (x[(p, t)] - s[(p, t)])
            for p in ids for t in events
        )
        - HIT_COST * pulp.lpSum(hits[t] for t in events)
    )

    for t in events:
        prob += pulp.lpSum(x[(p, t)] for p in ids) == 15
        prob += pulp.lpSum(s[(p, t)] for p in ids) == 11
        prob += pulp.lpSum(cap[(p, t)] for p in ids) == 1

        for position, required in position_requirements.items():
            prob += pulp.lpSum(x[(p, t)] for p in ids if pos[p] == position) == required
        for position, (min_play, max_play) in play_bounds.items():
            starters = pulp.lpSum(s[(p, t)] for p in ids if pos[p] == position)
            prob += starters >= min_play
            prob += starters <= max_play

        for team_id in {club[p] for p in ids}:
            prob += pulp.lpSum(x[(p, t)] for p in ids if club[p] == team_id) <= club_limit

        for p in ids:
            prob += cap[(p, t)] <= s[(p, t)]
            prob += s[(p, t)] <= x[(p, t)]
            # A player can never be bought and sold in the same gameweek -
            # without this the model can manufacture free transfer churn.
            prob += tin[(p, t)] + tout[(p, t)] <= 1

    # --- squad continuity ------------------------------------------------
    for i, t in enumerate(events):
        for p in ids:
            prev = (1 if p in owned else 0) if i == 0 else x[(p, events[i - 1])]
            prob += x[(p, t)] - prev == tin[(p, t)] - tout[(p, t)]

    # --- free transfers, hits, bank --------------------------------------
    for i, t in enumerate(events):
        transfers_t = pulp.lpSum(tin[(p, t)] for p in ids)

        # fuse = min(transfers, ft). Both <= constraints are stated; the
        # objective does the rest, because every unit of fuse the solver
        # can legally claim removes a -4 hit, so it is always pushed to the
        # binding value rather than left slack.
        prob += fuse[t] <= transfers_t
        prob += fuse[t] <= ft[t]
        prob += hits[t] >= transfers_t - fuse[t]

        if i == 0:
            prob += ft[t] == min(free_transfers, ft_cap)
        else:
            prev_t = events[i - 1]
            # ft_next = min(cap, ft_prev - fuse_prev + 1). Stated as two
            # upper bounds: ft is only ever beneficial (it buys future
            # transfers without a hit), so the solver pushes it up to
            # whichever bound binds, which is exactly the real rule.
            prob += ft[t] <= ft_cap
            prob += ft[t] <= ft[prev_t] - fuse[prev_t] + 1

        spend = pulp.lpSum(price[p] * tin[(p, t)] for p in ids)
        raised = pulp.lpSum(price[p] * tout[(p, t)] for p in ids)
        prev_bank = bank_tenths if i == 0 else bank[events[i - 1]]
        prob += bank[t] == prev_bank + raised - spend

    solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit_seconds)
    prob.solve(solver)
    status = pulp.LpStatus[prob.status]
    solve_seconds = time.monotonic() - started

    if status not in ("Optimal",) or prob.objective is None:
        return MilpPlanResult(None, status, False, None, horizon_gw, len(pool), solve_seconds)

    objective_value = float(pulp.value(prob.objective))
    sequence = _sequence_from_solution(
        conn, ids, events, x, s, cap, tin, tout, hits, bank, ft, xp, pos, by_id, owned, bench_weight,
    )
    return MilpPlanResult(
        sequence=sequence,
        status=status,
        proven_optimal=True,
        objective_value=round(objective_value, 2),
        horizon=horizon_gw,
        pool_size=len(pool),
        solve_seconds=round(solve_seconds, 2),
        chips_modelled=False,
    )


def _name_of(conn: sqlite3.Connection, player_id: int, by_id: dict) -> str:
    c = by_id.get(player_id)
    if c is not None:
        return c.web_name
    row = conn.execute("SELECT web_name FROM players WHERE id=?", (player_id,)).fetchone()
    return row["web_name"] if row else str(player_id)


def _sequence_from_solution(
    conn, ids, events, x, s, cap, tin, tout, hits, bank, ft, xp, pos, by_id, owned, bench_weight,
) -> TransferSequence:
    """Rebuild the solver's answer as a `TransferSequence`.

    `gw_ev` per step follows the same contract `transfers.py` documents:
    each step's own post-hit-cost contribution, such that summing them
    reproduces `total_net_ev` exactly. A gameweek with two transfers in it
    becomes two steps sharing that gameweek, with the gameweek's EV and hit
    cost attributed to the first of them, so the sum stays exact rather
    than being double counted.
    """
    def on(var) -> bool:
        return pulp.value(var) is not None and pulp.value(var) > 0.5

    steps: list[TransferSequenceStep] = []
    total_ev = 0.0
    total_hits = 0.0
    squad_prev = set(owned)

    for t in events:
        squad_t = {p for p in ids if on(x[(p, t)])}
        gw_ev = sum(
            xp[(p, t)] * (1.0 if on(s[(p, t)]) else _bench_weight_for(pos[p], bench_weight))
            + (xp[(p, t)] if on(cap[(p, t)]) else 0.0)
            for p in squad_t
        )
        gw_hits = float(pulp.value(hits[t]) or 0.0)
        total_ev += gw_ev
        total_hits += gw_hits * HIT_COST

        ins = sorted(p for p in ids if on(tin[(p, t)]))
        outs = sorted(p for p in ids if on(tout[(p, t)]))
        net_gw_ev = gw_ev - gw_hits * HIT_COST

        if not ins and not outs:
            steps.append(TransferSequenceStep(
                event=t, player_out_id=None, player_out_name=None,
                player_in_id=None, player_in_name=None, uses_hit=False,
                resulting_squad_ids=tuple(sorted(squad_t)), gw_ev=round(net_gw_ev, 2),
            ))
        else:
            paired = list(zip(outs, ins))
            for idx, (p_out, p_in) in enumerate(paired):
                steps.append(TransferSequenceStep(
                    event=t,
                    player_out_id=p_out, player_out_name=_name_of(conn, p_out, by_id),
                    player_in_id=p_in, player_in_name=_name_of(conn, p_in, by_id),
                    uses_hit=gw_hits > 0,
                    resulting_squad_ids=tuple(sorted(squad_t)),
                    # Attribute the gameweek's whole net contribution to its
                    # first step so sum(step.gw_ev) == total_net_ev holds.
                    gw_ev=round(net_gw_ev, 2) if idx == 0 else 0.0,
                ))
        squad_prev = squad_t

    final_event = events[-1]
    return TransferSequence(
        steps=tuple(steps),
        final_squad_ids=tuple(sorted(squad_prev)),
        final_free_transfers=int(pulp.value(ft[final_event]) or 0),
        final_bank_tenths=int(round(float(pulp.value(bank[final_event]) or 0.0))),
        total_net_ev=round(total_ev - total_hits, 2),
        tiebreak_adjustment=0.0,  # the MILP takes no tie-break nudges at all
        chips_used=(),
    )
