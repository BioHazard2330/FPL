"""The week plan's transfer policy replayed over a whole historical season, leakage-free.

`season_backtest.py` replays the old single-swap-or-roll rule. This replays the policy the week plan actually uses: the
exact multi-gameweek MILP (`milp_planner.plan_transfers_milp`) over a `HORIZON` window, free transfers banked up to the
cap of five, hits allowed when they pay, every transfer charged `BAR` points in the objective (the road-ahead form of the
week plan's per-move bar), and only the first gameweek's moves executed before re-planning next round. Three policies
start from the same round-0 squad and are scored on the same real reconstructed points with the eleven and armband picked
from each round's projections:

- PLAN: the week plan's solver, as above;
- SWAP: one like-for-like transfer a round when it clears the old 2.0-point bar (`season_backtest`'s rule);
- HOLD: never transfer.

Inputs are `season_backtest`'s: per-round projections from `harness.predict_player_round_points` (walk-forward, core
points only: appearance, goals, assists, cards), historical prices and clubs from the free archive. Disclosed limits, all
applied to every policy alike: the projection carries no fixture difficulty, clean sheets, bonus or defensive points, so
each gameweek in the horizon gets the same value and the replay tests transfer logic (how many, when, banking, hits), not
fixture planning; no chips; no auto-substitutes; sell price is the current price. After `COLD_START_ROUNDS` rounds a
player with no in-season projection is out of the pool (see `_candidates`); a squad member who drops out is valued at zero
(every policy alike)."""
import sqlite3
from dataclasses import dataclass, field

from fpl_agent.backtesting.harness import _round_start_dates
from fpl_agent.backtesting.season_backtest import (
    _TRANSFER_MATERIALITY_BAR,
    _best_single_transfer,
    _build_candidates,
    _build_initial_squad,
    _candidate_universe,
    _real_round_points,
)
from fpl_agent.optimization.milp_planner import HIT_COST, plan_transfers_milp
from fpl_agent.optimization.squad import PlayerCandidate, pick_starting_xi

HORIZON = 5
BAR = 1.5
FT_CAP = 5
POOL_PER_POSITION = 20
SOLVE_SECONDS = 30


@dataclass
class PolicyRun:
    name: str
    squad: list[PlayerCandidate]
    bank: int = 0
    free_transfers: int = 1
    points: float = 0.0
    hits: int = 0
    transfers: int = 0
    rounds: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class PlanReplayResult:
    season: str
    rounds: int
    totals: dict[str, float]
    transfers: dict[str, int]
    hits: dict[str, int]
    per_round: list[dict]
    unproven_solves: int


COLD_START_ROUNDS = 4


def _candidates(conn, universe, season: str, round_start: str, i: int) -> list[PlayerCandidate]:
    """`season_backtest._build_candidates`, except that once `COLD_START_ROUNDS` rounds have passed a player with no
    in-season projection (fewer than four matches this season) is not valued at last season's rate: he has not been
    playing, which the live minutes model sees and the replay's core projection does not."""
    import fpl_agent.backtesting.season_backtest as sb

    if i < COLD_START_ROUNDS:
        return _build_candidates(conn, universe, season, round_start, "historical_gw", gw=i + 1)[0]
    original = sb._round_value
    sb._round_value = lambda c, pid, s, d, pos: sb.predict_player_round_points(c, pid, s, d, pos)
    try:
        return _build_candidates(conn, universe, season, round_start, "historical_gw", gw=i + 1)[0]
    finally:
        sb._round_value = original


def _with_club_ids(candidates: list[PlayerCandidate]) -> list[PlayerCandidate]:
    """The MILP's three-per-club rule groups by `team_id`; the replay's clubs are the historical ones in `team_short`."""
    ids = {short: 10_000 + i for i, short in enumerate(sorted({c.team_short for c in candidates}))}
    return [PlayerCandidate(**{**c.__dict__, "team_id": ids[c.team_short]}) for c in candidates]


def _score(conn, season: str, run: PolicyRun, round_start: str, round_end: str | None, unreliable: frozenset[int]) -> float:
    xi = pick_starting_xi(conn, run.squad)
    pts, _ = _real_round_points(
        conn, season, xi.starting, xi.captain.player_id if xi.captain else None, round_start, round_end, unreliable,
    )
    return pts


def run_plan_replay(conn: sqlite3.Connection, season: str, max_rounds: int | None = None) -> PlanReplayResult:
    from fpl_agent.backtesting.data_fidelity import MISSING_DATA, UNRESOLVED_ID, diagnose_season

    starts = _round_start_dates(conn, season)
    if not starts:
        raise ValueError(f"no rounds for {season}")
    boundaries = starts + [None]
    if max_rounds:
        starts = starts[:max_rounds]
    universe, _, _ = _candidate_universe(conn, season, "historical")
    round0, _, _ = _build_candidates(conn, universe, season, starts[0], "historical_gw", gw=1)
    squad0 = _build_initial_squad(round0)
    if squad0 is None:
        raise ValueError(f"round-0 squad infeasible for {season}")
    unreliable = frozenset(s.player_id for s in diagnose_season(conn, season) if s.derived_status in (MISSING_DATA, UNRESOLVED_ID))

    runs = {name: PolicyRun(name, list(squad0)) for name in ("plan", "swap", "hold")}
    per_round = []
    unproven = 0
    for i, round_start in enumerate(starts):
        round_end = boundaries[i + 1]
        candidates = _with_club_ids(_candidates(conn, universe, season, round_start, i))
        by_id = {c.player_id: c for c in candidates}
        for run in runs.values():
            run.squad = [
                by_id.get(c.player_id) or (c if i < COLD_START_ROUNDS else PlayerCandidate(**{**c.__dict__, "xp": 0.0, "median": 0.0}))
                for c in run.squad
            ]

        if i > 0:
            plan = runs["plan"]
            owned = {c.player_id for c in plan.squad}
            pool = candidates + [c for c in plan.squad if c.player_id not in by_id]
            cache = {(c.player_id, i + 1 + k): c.xp for c in pool for k in range(HORIZON)}
            result = plan_transfers_milp(
                conn, [c.player_id for c in plan.squad], plan.free_transfers, plan.bank, start_event=i + 1,
                horizon_gw=HORIZON, pool_per_position=POOL_PER_POSITION, time_limit_seconds=SOLVE_SECONDS,
                model_chips=False, xp_cache=cache, league_pool=pool, transfer_penalty=BAR,
            )
            used = 0
            if result.sequence is not None:
                unproven += 0 if result.proven_optimal else 1
                first = [st for st in result.sequence.steps if st.event == i + 1 and st.player_in_id is not None]
                pool_by_id = {c.player_id: c for c in pool}
                for st in first:
                    out = next(c for c in plan.squad if c.player_id == st.player_out_id)
                    into = pool_by_id[st.player_in_id]
                    plan.bank += out.price_tenths - into.price_tenths
                    plan.squad = [into if c.player_id == out.player_id else c for c in plan.squad]
                    used += 1
                assert len({c.player_id for c in plan.squad}) == 15 and owned is not None
            hits = max(0, used - plan.free_transfers)
            plan.hits += hits
            plan.points -= hits * HIT_COST
            plan.transfers += used
            plan.free_transfers = min(max(plan.free_transfers - used, 0) + 1, FT_CAP)

            swap = runs["swap"]
            pool_by_position: dict[str, list[PlayerCandidate]] = {}
            for c in candidates:
                pool_by_position.setdefault(c.position, []).append(c)
            best = _best_single_transfer(swap.squad, pool_by_position, swap.bank)
            if best is not None and best[2] > _TRANSFER_MATERIALITY_BAR:
                out, into, _ = best
                swap.bank = max(0, out.price_tenths + swap.bank - into.price_tenths)
                swap.squad = [into if c.player_id == out.player_id else c for c in swap.squad]
                swap.transfers += 1

        row = {"round": i + 1}
        for name, run in runs.items():
            pts = _score(conn, season, run, round_start, round_end, unreliable)
            run.points += pts
            run.rounds.append(pts)
            row[name] = round(pts, 1)
        per_round.append(row)

    return PlanReplayResult(
        season=season, rounds=len(starts),
        totals={n: round(r.points, 1) for n, r in runs.items()},
        transfers={n: r.transfers for n, r in runs.items()},
        hits={n: r.hits for n, r in runs.items()},
        per_round=per_round, unproven_solves=unproven,
    )
