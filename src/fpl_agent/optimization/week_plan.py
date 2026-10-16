"""This gameweek's transfer decision, planned as a set rather than a single swap.

The beam search behind `strategic_planner.py` makes at most one transfer per
gameweek. A manager sitting on five free transfers (the cap) was therefore
handed one swap worth a point or two, while the planner's own cross-check
showed the exact solver finding 13-29 more points over five gameweeks. Rolling
at the cap also throws a transfer away, which no single-swap planner can say.

This module asks the question the manager is actually facing: given the real
squad, free transfers and bank, which moves do I make this gameweek, and what
does each one earn? It uses `milp_planner` for the arithmetic (squad rules,
free-transfer rollover with the cap, hit costs, XI selection) and builds the
answer one move at a time:

1. Price rolling this gameweek and re-planning optimally from the next.
2. Add the single best first-gameweek transfer to that. Then force it, and add
   the best second one on top. Repeat while the move still earns its keep.

Each move therefore has a marginal value measured against the best plan that
already contains the moves before it, and the list is nested: stopping early
never changes the moves above the stopping point.

Assumptions, stated rather than discovered later:
- `MIN_MOVE_GAIN` (points over the horizon, net of any hit) is the least a move
  must add to be recommended. It is a judgement, not a fitted value: the
  model's measured per-player error is 2.8 points, so a move worth a single
  point over five gameweeks is indistinguishable from nothing.
- Projections are the same per-gameweek expected points the beam search uses,
  including the start-probability discount, so any disagreement between the two
  planners is search, not valuation.
- Sell prices use the current price. FPL pays purchase price plus half the
  profit, and this project cannot read purchase prices reliably, so
  `affordability` reports whether the plan still fits under the strictest
  reconstruction available.
- Captain: the top projection takes the armband unless another starter is within
  `CAPTAIN_TIE_BAND` points of it, in which case the one whose points come more
  from goals and assists does. A doubled appearance or clean-sheet point is the
  least valuable thing a captain can return.
- Lineup: the manager's current eleven is kept wherever a better player at the
  same position is ahead by less than `LINEUP_MIN_SWAP_GAIN` expected points. A
  tenth of a point is not a reason to rebuild a lineup, and a tool that says
  otherwise is not credible about the swaps that matter.
- The road ahead (`LONG_HORIZON_GW` gameweeks) is the same solver with each
  transfer charged `MIN_MOVE_GAIN` in the objective, so a later week makes a
  move only if it would earn the same bar this week's moves had to. It is a
  projection of how this week's plan continues, never a set of decisions.
- Chips are not part of the decision. Free hit is never modelled; wildcard,
  bench boost and triple captain are left to `chips.py`.
"""
import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone

from fpl_agent.database.decisions import latest_decision_of_type, log_decision
from fpl_agent.optimization.locked_squad import LockedSquadState, get_locked_squad
from fpl_agent.optimization.milp_planner import plan_transfers_milp
from fpl_agent.optimization.squad import _BENCH_WEIGHT, PlayerCandidate, build_player_pool, resolve_projected_xi

_logger = logging.getLogger("fpl_agent.week_plan")

def assumptions(min_move_gain: float, horizon: int, mae: float | None) -> list[str]:
    """What the plan rests on, in the words the ADVANCED screen shows. The
    measured error is passed in rather than written here, so the text can never
    quote a number the calibration table has since moved off."""
    error = (
        f"the model's measured error is {mae:.1f} points per player per gameweek" if mae is not None
        else "there are too few settled predictions to measure the model's error yet"
    )
    return [
        f"A transfer has to add {min_move_gain:g} points over {horizon} gameweeks to be recommended. That is a judgement, "
        f"not a fitted number: {error}.",
        "Sell prices are current prices. FPL pays purchase price plus half the rise, which this project cannot read "
        "reliably, so the plan reports whether it still fits under the strictest reading.",
        "Every projection comes from the one model. Solio's is shown beside the player coming in as a check and never feeds it.",
        "A predicted start percentage discounts the next gameweek's minutes in full and half as much for each gameweek after. "
        "It is not calibrated: there is no history of that feed to fit it to.",
        f"The moves are judged by points over {horizon} gameweeks. Price changes, double gameweeks not yet announced and "
        "chips are outside the decision.",
    ]


DECISION_TYPE = "week_plan"
HORIZON_GW = 5
MIN_MOVE_GAIN = 1.5
POOL_PER_POSITION = 25
SOLVE_SECONDS = 60
CAPTAIN_TIE_BAND = 0.5
LINEUP_MIN_SWAP_GAIN = 0.4
LONG_HORIZON_GW = 8
FREE_TRANSFER_CAP = 5


@dataclass(frozen=True)
class PlayerRef:
    player_id: int
    name: str
    position: str
    team_short: str
    team_id: int
    price_tenths: int
    xp_next: float
    xp_horizon: float
    start_percent: int | None
    price_trend: str
    solio_next: float | None
    duties: list[str] = field(default_factory=list)
    match_analysis_xp: float = 0.0


@dataclass(frozen=True)
class MoveStress:
    gain_with_others: float
    gain_if_half: float
    breakeven_drop_pct: float | None
    survives_half: bool


@dataclass(frozen=True)
class Alternative:
    out: PlayerRef
    into: PlayerRef
    gain: float
    cost_tenths: int


@dataclass(frozen=True)
class PlannedMove:
    out: PlayerRef
    into: PlayerRef
    gain: float
    cost_tenths: int
    stress: MoveStress | None = None
    timing: str = "any"
    timing_note: str = ""
    alternatives: list[Alternative] = field(default_factory=list)


@dataclass(frozen=True)
class LineupPlayer:
    player_id: int
    name: str
    position: str
    team_short: str
    team_id: int
    xp: float
    start_percent: int | None
    floor: float | None = None
    ceiling: float | None = None


@dataclass(frozen=True)
class Lineup:
    starting: list[LineupPlayer]
    bench: list[LineupPlayer]
    captain_id: int | None
    vice_id: int | None
    xp_total: float
    captain_note: str | None = None


@dataclass(frozen=True)
class CurveStep:
    moves: int
    total: float
    gain_vs_roll: float


@dataclass(frozen=True)
class WeekPlan:
    event: int
    horizon: int
    free_transfers: int
    free_transfers_known: bool
    bank_tenths: int
    roll_total: float
    plan_total: float
    gain_vs_roll: float
    moves: list[PlannedMove]
    declined: list[PlannedMove]
    curve: list[CurveStep]
    ft_after: int
    bank_after_tenths: int
    affordability: str
    lineup_now: Lineup
    lineup_after: Lineup
    lineup_set_by_you: Lineup | None
    road_ahead: dict | None
    chip_outlook: dict
    solver: dict
    proven_optimal: bool
    min_move_gain: float
    squad_ids: list[int]
    computed_at: str
    notes: list[str] = field(default_factory=list)
    captain_ladder: list[dict] = field(default_factory=list)
    team_outlook: dict = field(default_factory=dict)


def _start_percents(conn: sqlite3.Connection, ids: set[int]) -> dict[int, int]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT player_id, start_percent FROM player_start_probability WHERE player_id IN ({marks})", tuple(ids),
    ).fetchall()
    return {r["player_id"]: r["start_percent"] for r in rows}


def _solio_next(conn: sqlite3.Connection, ids: set[int]) -> dict[int, float]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT player_id, pr_points FROM solio_player_projection WHERE snapshot_id="
        f"(SELECT MAX(id) FROM solio_snapshot) AND player_id IN ({marks})", tuple(ids),
    ).fetchall()
    return {r["player_id"]: r["pr_points"] for r in rows if r["pr_points"] is not None}


def _set_piece_duties(conn: sqlite3.Connection, ids: set[int]) -> dict[int, list[str]]:
    """First-choice set-piece duties, from the FPL site's own set-piece notes. A
    penalty taker is worth roughly half a point a match on his own, and a player
    whose duty changed this month has no history in the goal-share a projection
    is built from, so the model cannot see it - the plan shows it instead."""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT player_id, penalties_order, corners_order, direct_fk_order FROM player_setpiece_history "
        f"WHERE valid_until IS NULL AND player_id IN ({marks})", tuple(ids),
    ).fetchall()
    out: dict[int, list[str]] = {}
    for r in rows:
        duties = [
            label for label, order in (
                ("penalties", r["penalties_order"]), ("free kicks", r["direct_fk_order"]), ("corners", r["corners_order"]),
            ) if order == 1
        ]
        if duties:
            out[r["player_id"]] = duties
    return out


def _price_trends(conn: sqlite3.Connection, ids: set[int]) -> dict[int, str]:
    from fpl_agent.models.price_forecast import classify_price_change

    return {pid: classify_price_change(conn, pid).direction for pid in ids}


def pick_captains(starting: list[PlayerCandidate], xp_cache: dict, event: int):
    ranked = sorted(starting, key=lambda c: c.xp, reverse=True)
    if not ranked:
        return None, None

    def attacking(c: PlayerCandidate) -> float:
        projection = xp_cache.get((c.player_id, event))
        parts = getattr(projection, "components", None)
        return (parts.goals + parts.assists) if parts is not None else 0.0

    contenders = [c for c in ranked if ranked[0].xp - c.xp <= CAPTAIN_TIE_BAND]
    captain = max(contenders, key=lambda c: (attacking(c), c.xp))
    others = [c for c in ranked if c.player_id != captain.player_id]
    vice = next((c for c in others if c.team_id != captain.team_id), others[0] if others else None)
    return captain, vice


def prefer_current_eleven(
    starting: list[PlayerCandidate], bench: list[PlayerCandidate], current_ids: set[int],
    min_gain: float = LINEUP_MIN_SWAP_GAIN,
) -> tuple[list[PlayerCandidate], list[PlayerCandidate]]:
    start, benched = list(starting), list(bench)
    for incoming in sorted((c for c in start if c.player_id not in current_ids), key=lambda c: c.xp):
        keepers = [
            b for b in benched
            if b.player_id in current_ids and b.position == incoming.position and incoming.xp - b.xp < min_gain
        ]
        if keepers:
            restored = max(keepers, key=lambda c: c.xp)
            start[start.index(incoming)] = restored
            benched[benched.index(restored)] = incoming
    return start, benched


def _lineup(
    conn: sqlite3.Connection, squad_ids: set[int], event: int, xp_cache: dict, starts: dict[int, int],
    current_xi_ids: set[int] | None = None,
) -> Lineup:
    xi = resolve_projected_xi(conn, squad_ids, event, xp_cache=xp_cache)
    if current_xi_ids:
        kept_start, kept_bench = prefer_current_eleven(xi.starting, xi.bench, current_xi_ids)
        xi = type(xi)(starting=kept_start, bench=kept_bench, captain=None, vice_captain=None)

    def row(c: PlayerCandidate) -> LineupPlayer:
        return LineupPlayer(
            player_id=c.player_id, name=c.web_name, position=c.position, team_short=c.team_short,
            team_id=c.team_id, xp=round(c.xp, 2), start_percent=starts.get(c.player_id),
            floor=round(c.floor, 2), ceiling=round(c.ceiling, 2),
        )

    starting_order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
    starting = sorted(xi.starting, key=lambda c: (starting_order[c.position], -c.xp))
    keepers = [c for c in xi.bench if c.position == "GKP"]
    outfield = [c for c in xi.bench if c.position != "GKP"]
    bench = keepers + outfield
    captain, vice = pick_captains(xi.starting, xp_cache, event)
    top = max(xi.starting, key=lambda c: c.xp, default=None)
    captain_note = None
    if captain is not None and top is not None and captain.player_id != top.player_id:
        captain_note = (
            f"{captain.web_name} over {top.web_name}: the projections are within {CAPTAIN_TIE_BAND:g} xP, "
            f"and more of his points come from goals and assists."
        )
    return Lineup(
        starting=[row(c) for c in starting], bench=[row(c) for c in bench],
        captain_id=captain.player_id if captain else None, vice_id=vice.player_id if vice else None,
        xp_total=round(sum(c.xp for c in xi.starting) + (captain.xp if captain else 0.0), 2),
        captain_note=captain_note,
    )


def _lineup_as_set(locked: LockedSquadState, xp_by_id: dict[int, float], starts: dict[int, int]) -> Lineup | None:
    xi = locked.xi
    if not xi.starting:
        return None

    def row(c) -> LineupPlayer:
        return LineupPlayer(
            player_id=c.player_id, name=c.web_name, position=c.position, team_short=c.team_short,
            team_id=c.team_id, xp=round(xp_by_id.get(c.player_id, c.xp), 2), start_percent=starts.get(c.player_id),
            floor=round(c.floor, 2), ceiling=round(c.ceiling, 2),
        )

    starting = sorted(xi.starting, key=lambda c: ({"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}[c.position], -c.xp))
    captain_id = xi.captain.player_id if xi.captain else None
    xp_total = sum(xp_by_id.get(c.player_id, c.xp) for c in xi.starting) + (
        xp_by_id.get(captain_id, 0.0) if captain_id is not None else 0.0
    )
    return Lineup(
        starting=[row(c) for c in starting], bench=[row(c) for c in xi.bench],
        captain_id=captain_id, vice_id=xi.vice_captain.player_id if xi.vice_captain else None,
        xp_total=round(xp_total, 2),
    )


def _strict_sell_shortfall_tenths(conn: sqlite3.Connection, out_ids: list[int]) -> int:
    """Largest amount the sales could raise below current price, if purchase
    prices are what the transfer log says. FPL pays back half of any rise."""
    from fpl_agent.ingestion.my_team import get_my_team_entry_id

    entry_id = get_my_team_entry_id(conn)
    if entry_id is None:
        return 0
    free_hit_events = {
        r["event"] for r in conn.execute(
            "SELECT DISTINCT event FROM my_team_picks WHERE entry_id=? AND active_chip='freehit'", (entry_id,),
        ).fetchall()
    }
    transfers = [
        dict(r) for r in conn.execute(
            "SELECT * FROM my_team_transfers WHERE entry_id=? ORDER BY transfer_time", (entry_id,),
        ).fetchall()
    ]
    first_deadline = conn.execute("SELECT deadline_time FROM events WHERE id=1").fetchone()
    shortfall = 0
    for pid in out_ids:
        current = conn.execute(
            "SELECT value_tenths FROM player_price_history WHERE player_id=? AND valid_until IS NULL", (pid,),
        ).fetchone()
        if current is None:
            continue
        ins = [t for t in transfers if t["element_in"] == pid and t["event"] not in free_hit_events]
        outs = [t for t in transfers if t["element_out"] == pid and t["event"] not in free_hit_events]
        if ins and (not outs or ins[-1]["transfer_time"] > outs[-1]["transfer_time"]):
            bought = ins[-1]["element_in_cost"]
        else:
            row = conn.execute(
                "SELECT value_tenths FROM player_price_history WHERE player_id=? AND valid_from<=? "
                "ORDER BY valid_from DESC LIMIT 1", (pid, first_deadline["deadline_time"] if first_deadline else ""),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT value_tenths FROM player_price_history WHERE player_id=? ORDER BY valid_from ASC LIMIT 1",
                    (pid,),
                ).fetchone()
            bought = row["value_tenths"] if row else current["value_tenths"]
        if current["value_tenths"] > bought:
            shortfall += current["value_tenths"] - (bought + (current["value_tenths"] - bought) // 2)
    return shortfall


def move_timing(out: "PlayerRef", into: "PlayerRef") -> tuple[str, str]:
    """When to make a move, not whether to. A price that is moving against you
    makes waiting cost money; a rotation call that is still open makes acting
    early cost information, because team news lands before the deadline. When
    both are true the move is marked as such rather than resolved by a guess."""
    price_moving = into.price_trend == "RISE_LIKELY" or out.price_trend == "FALL_LIKELY"
    doubts = [p for p in (out, into) if p.start_percent is not None and p.start_percent < 70]
    if price_moving and doubts:
        return "split", (
            f"The price is moving, but {doubts[0].name}'s start is not settled ({doubts[0].start_percent}%). "
            "Waiting risks a price change; acting risks the team news."
        )
    if price_moving:
        mover = into.name if into.price_trend == "RISE_LIKELY" else out.name
        direction = "rise" if into.price_trend == "RISE_LIKELY" else "fall"
        return "early", f"{mover} is likely to {direction} in price. Make this before the next overnight price change."
    if doubts:
        return "late", (
            f"{doubts[0].name}'s start is in doubt ({doubts[0].start_percent}%). "
            "Team news lands before the deadline: wait for it."
        )
    return "any", ""


def _ref(
    c: PlayerCandidate, xp_next: float, starts: dict, trends: dict, solio: dict, duties: dict, match_xp: dict,
) -> PlayerRef:
    return PlayerRef(
        duties=duties.get(c.player_id, []), match_analysis_xp=round(match_xp.get(c.player_id, 0.0), 2),
        player_id=c.player_id, name=c.web_name, position=c.position, team_short=c.team_short, team_id=c.team_id,
        price_tenths=c.price_tenths, xp_next=round(xp_next, 2), xp_horizon=round(c.xp, 2),
        start_percent=starts.get(c.player_id), price_trend=trends.get(c.player_id, "STABLE"),
        solio_next=round(solio[c.player_id], 2) if c.player_id in solio else None,
    )


@dataclass(frozen=True)
class _Selection:
    accepted: list
    declined: list
    curve: list
    final: object
    proven: bool
    roll_total: float
    first_moves: object


def _first_moves(result, event: int) -> list[tuple[int, int]]:
    steps = [s for s in result.sequence.steps if s.event == event and s.player_in_id is not None]
    return [(s.player_out_id, s.player_in_id) for s in steps]


def select_moves(solve, event: int, min_move_gain: float, max_moves: int = 5) -> _Selection | None:
    """Builds the move list one transfer at a time. `solve(k, forced_in,
    forced_out)` must return the best plan that makes at most `k` first-
    gameweek transfers and includes the forced ones; `solve(0)` is rolling now.
    A move is kept while the plan it produces beats the previous plan by at
    least `min_move_gain`. The first move that does not is reported as
    declined, never silently dropped."""
    roll = solve(0, frozenset(), frozenset())
    if roll.sequence is None:
        return None
    roll_total = roll.sequence.total_net_ev
    proven = roll.proven_optimal
    accepted: list[tuple[int, int, float]] = []
    declined: list[tuple[int, int, float]] = []
    curve = [CurveStep(0, roll_total, 0.0)]
    previous_total = roll_total
    final = roll
    forced_in: frozenset[int] = frozenset()
    forced_out: frozenset[int] = frozenset()
    for k in range(1, max_moves + 1):
        trial = solve(k, forced_in, forced_out)
        proven = proven and trial.proven_optimal
        if trial.sequence is None:
            break
        total = trial.sequence.total_net_ev
        gain = total - previous_total
        curve.append(CurveStep(k, total, round(total - roll_total, 2)))
        new = [m for m in _first_moves(trial, event) if m[1] not in forced_in]
        if not new:
            break
        if gain < min_move_gain:
            declined.append((new[0][0], new[0][1], round(gain, 2)))
            break
        accepted.append((new[0][0], new[0][1], round(gain, 2)))
        pairs = _first_moves(trial, event)
        forced_in = frozenset(i for _, i in pairs)
        forced_out = frozenset(o for o, _ in pairs)
        previous_total = total
        final = trial
    return _Selection(accepted, declined, curve, final, proven, roll_total, lambda result: _first_moves(result, event))


def build_chip_outlook(conn: sqlite3.Connection, event: int, bench_xp_this_week: float, horizon: int = LONG_HORIZON_GW) -> dict:
    """Which chips are still available, and whether the fixture list gives any of
    them a reason to be played. A bench boost on an ordinary gameweek returns
    the bench's expected points and nothing else; its value comes from a double
    gameweek, so the outlook states plainly whether one is scheduled."""
    from fpl_agent.ingestion.my_team import get_my_team_entry_id, get_used_chips
    from fpl_agent.models.fixtures import detect_blank_double_gws

    entry_id = get_my_team_entry_id(conn)
    used = get_used_chips(conn, entry_id, event) if entry_id is not None else set()
    available = [c for c in ("wildcard", "freehit", "bboost", "3xc") if c not in used]
    anomalies = detect_blank_double_gws(conn, event, horizon)
    doubles: dict[int, list[str]] = {}
    blanks: dict[int, list[str]] = {}
    for a in anomalies:
        (doubles if a.kind == "double" else blanks).setdefault(a.event, []).append(a.team_short_name)
    return {
        "available": available,
        "double_gameweeks": [{"event": e, "teams": sorted(t)} for e, t in sorted(doubles.items())],
        "blank_gameweeks": [{"event": e, "teams": sorted(t)} for e, t in sorted(blanks.items())],
        "bench_boost_this_week": round(bench_xp_this_week, 1),
        "horizon": horizon,
    }


def build_road_ahead(
    conn: sqlite3.Connection, squad_ids: list[int], free_transfers: int, bank: int, event: int, pool: list,
    cache: dict, pairs: list[tuple[int, int]], min_move_gain: float, horizon: int = LONG_HORIZON_GW,
) -> dict | None:
    """How the plan continues over a longer horizon, given this week's moves.
    Weeks with no move are kept as explicit rolls: they carry the free-transfer
    bank, which is the point of waiting."""
    common = dict(
        start_event=event, horizon_gw=horizon, pool_per_position=POOL_PER_POSITION, bench_weight=_BENCH_WEIGHT,
        time_limit_seconds=SOLVE_SECONDS, model_chips=False, xp_cache=cache, league_pool=pool,
        transfer_penalty=min_move_gain,
    )
    plan = plan_transfers_milp(
        conn, squad_ids, free_transfers, bank, max_first_gw_transfers=len(pairs),
        forced_in_first=frozenset(i for _, i in pairs), forced_out_first=frozenset(o for o, _ in pairs), **common,
    )
    roll = plan_transfers_milp(conn, squad_ids, free_transfers, bank, max_first_gw_transfers=0, **common)
    if plan.sequence is None or roll.sequence is None:
        return None
    weeks = []
    for e in range(event, event + horizon):
        weeks.append({
            "event": e,
            "moves": [
                {"out": s.player_out_name, "into": s.player_in_name, "hit": bool(s.uses_hit)}
                for s in plan.sequence.steps if s.event == e and s.player_in_id is not None
            ],
        })
    banked = free_transfers
    for week in weeks:
        banked = min(banked - min(len(week["moves"]), banked) + 1, FREE_TRANSFER_CAP)
    return {
        "horizon": horizon, "total": plan.sequence.total_net_ev, "roll_total": roll.sequence.total_net_ev,
        "gain_vs_roll": round(plan.sequence.total_net_ev - roll.sequence.total_net_ev, 2),
        "proven": plan.proven_optimal and roll.proven_optimal, "weeks": weeks,
        "final_free_transfers": banked,
    }


def stress_moves(solve, pairs: list[tuple[int, int]], bar: float, event: int) -> list[MoveStress | None]:
    """What each move is worth if the player coming in simply returns less than
    projected. `solve(k, forced_in, forced_out, scale)` is the same planner with
    that player's projection multiplied by `scale` in every gameweek. Each move
    is priced against the best plan that makes all the OTHER moves and nothing
    else, at full projection and at half. The drop that would take the move to
    the bar is read off the line between the two - an interpolation, not a third
    solve, and described as such where it is shown."""
    stresses: list[MoveStress | None] = []
    for _out_id, in_id in pairs:
        others = [p for p in pairs if p[1] != in_id]
        o_in, o_out = frozenset(i for _, i in others), frozenset(o for o, _ in others)
        try:
            values = {}
            for scale in (1.0, 0.5):
                with_move = solve(len(pairs), frozenset(i for _, i in pairs), frozenset(o for o, _ in pairs), {in_id: scale})
                without = solve(len(others), o_in, o_out, {in_id: scale})
                if with_move.sequence is None or without.sequence is None:
                    raise ValueError("unsolved")
                values[scale] = with_move.sequence.total_net_ev - without.sequence.total_net_ev
        except Exception:
            stresses.append(None)
            continue
        full, half = values[1.0], values[0.5]
        if full <= bar:
            breakeven = 0.0
        elif half >= bar:
            breakeven = None
        elif full - half > 1e-9:
            breakeven = round((full - bar) / (full - half) * 50.0, 0)
        else:
            breakeven = None
        stresses.append(MoveStress(
            gain_with_others=round(full, 2), gain_if_half=round(half, 2), breakeven_drop_pct=breakeven,
            survives_half=half >= bar,
        ))
    return stresses


ALTERNATIVES_PER_MOVE = 2


def find_alternatives(solve, pairs: list[tuple[int, int]], event: int, count: int = ALTERNATIVES_PER_MOVE):
    """For each move: the best way to spend the same transfer if the player
    coming in is not available, not wanted or has just been announced as injured.
    `solve(k, forced_in, forced_out, scale, banned)` is the planner with `banned`
    removed from the pool. Every other move stays forced, so an alternative is
    priced against the best plan that makes the other moves and never buys the
    banned player: with Cherki unavailable the question is what the slot is worth
    then, not what it was worth beside a plan that still buys him next week. The next alternative bans the one before, so the list is
    a ranking and not three versions of one idea. An alternative worth nothing or
    less is not listed: the honest answer there is that the slot is not worth
    spending."""
    found: list[list[tuple[int, int, float]]] = []
    for _out_id, in_id in pairs:
        others = [p for p in pairs if p[1] != in_id]
        o_in, o_out = frozenset(i for _, i in others), frozenset(o for o, _ in others)
        alts: list[tuple[int, int, float]] = []
        try:
            base = solve(len(others), o_in, o_out, None, frozenset({in_id}))
            if base.sequence is None:
                found.append(alts)
                continue
            banned = {in_id}
            for _ in range(count):
                trial = solve(len(pairs), o_in, o_out, None, frozenset(banned))
                if trial.sequence is None:
                    break
                new = [m for m in _first_moves(trial, event) if m[1] not in o_in]
                gain = trial.sequence.total_net_ev - base.sequence.total_net_ev
                if not new or gain <= 0:
                    break
                alts.append((new[0][0], new[0][1], round(gain, 2)))
                banned.add(new[0][1])
        except Exception:
            _logger.exception("alternative search failed for a move - the move itself is unaffected")
        found.append(alts)
    return found


def build_captain_ladder(conn: sqlite3.Connection, squad_after: set[int], event: int, horizon: int, xp_cache: dict) -> list[dict]:
    """Who takes the armband in each of the next gameweeks if this squad is kept.
    A pick that changes from week to week is information the manager needs
    before choosing between two similar targets: the player who captains for
    one week and is benched the next is worth less than the one who does it for
    four. Same expected points as the lineup, no extra model."""
    from fpl_agent.optimization.squad import build_player_pool_for_ids

    ladder = []
    for e in range(event, event + horizon):
        pool = build_player_pool_for_ids(conn, squad_after, e, xp_cache=xp_cache)
        ranked = sorted(pool, key=lambda c: c.xp, reverse=True)[:3]
        if ranked:
            ladder.append({
                "event": e,
                "picks": [{"player_id": c.player_id, "name": c.web_name, "team_id": c.team_id, "xp": round(c.xp, 2)} for c in ranked],
            })
    return ladder


def compact_team_outlook(conn: sqlite3.Connection, event: int) -> dict[str, dict]:
    """Every club's attack and defence standing over the next six gameweeks and
    its next fixture, keyed by team id, so each player in a transfer can be set
    against the football his club is about to play. See `models/fixture_outlook`."""
    from fpl_agent.models.fixture_outlook import team_fixture_outlook

    out = {}
    for tid, row in team_fixture_outlook(conn, event).items():
        first = row["events"].get(str(event)) or next(iter(row["events"].values()), [])
        out[str(tid)] = {
            "short": row["short"], "attack_rank": row["attack_rank"], "defence_rank": row["defence_rank"],
            "clubs": row["clubs_ranked"], "xg_for_total": row["xg_for_total"], "cs_total": row["cs_total"],
            "fixtures": row["fixtures"], "next": first,
        }
    return out


def build_week_plan(
    conn: sqlite3.Connection, horizon: int = HORIZON_GW, min_move_gain: float = MIN_MOVE_GAIN,
) -> WeekPlan | None:
    locked = get_locked_squad(conn)
    if locked is None or locked.source != "synced_real":
        return None
    squad_ids = [c.player_id for c in locked.xi.starting] + [c.player_id for c in locked.xi.bench]
    if len(squad_ids) != 15:
        return None
    event = locked.event + 1
    bank = int(round(locked.bank_tenths or 0))
    ft_known = locked.free_transfers is not None
    free_transfers = locked.free_transfers if ft_known else 1

    pool = build_player_pool(conn, n_gw=horizon)
    by_id = {c.player_id: c for c in pool}
    cache: dict = {}

    def solve(max_moves: int, fin, fout, scale=None, banned=frozenset()):
        return plan_transfers_milp(
            conn, squad_ids, free_transfers, bank, start_event=event, horizon_gw=horizon,
            pool_per_position=POOL_PER_POSITION, bench_weight=_BENCH_WEIGHT, time_limit_seconds=SOLVE_SECONDS,
            model_chips=False, xp_cache=cache, max_first_gw_transfers=max_moves,
            league_pool=[c for c in pool if c.player_id not in banned] if banned else pool,
            forced_in_first=frozenset(fin), forced_out_first=frozenset(fout), xp_scale=scale,
        )

    selection = select_moves(solve, event, min_move_gain)
    if selection is None:
        return None
    accepted, declined, curve, final, proven, roll_total = (
        selection.accepted, selection.declined, selection.curve, selection.final, selection.proven,
        selection.roll_total,
    )
    first_moves = selection.first_moves

    chosen_pairs = first_moves(final) if accepted else []
    plan_total = final.sequence.total_net_ev if accepted else roll_total

    squad_after = set(squad_ids)
    for o, i in chosen_pairs:
        squad_after.discard(o)
        squad_after.add(i)

    ordered_pairs = {i: o for o, i in chosen_pairs}
    move_pairs = [(ordered_pairs[i], i) for _, i, _ in accepted if i in ordered_pairs]
    found_alternatives = find_alternatives(solve, move_pairs, event) if move_pairs else []

    involved = {p for pair in chosen_pairs for p in pair} | {o for o, _, _ in declined} | {i for _, i, _ in declined}
    involved |= {p for alts in found_alternatives for o, i, _ in alts for p in (o, i)}
    starts = _start_percents(conn, set(squad_ids) | squad_after | involved)
    trends = _price_trends(conn, involved)
    solio = _solio_next(conn, set(squad_ids) | involved)
    duties = _set_piece_duties(conn, involved)
    next_xp_cache: dict = {}
    match_xp: dict[int, float] = {}

    from fpl_agent.models.expected_points import expected_points

    def next_xp(pid: int) -> float:
        if pid not in next_xp_cache:
            projection = expected_points(conn, pid, n_gw=1, from_event=event)
            next_xp_cache[pid] = projection.median
            match_xp[pid] = projection.qualitative_adjustment
        return next_xp_cache[pid]

    def candidate(pid: int) -> PlayerCandidate:
        c = by_id.get(pid)
        if c is not None:
            return c
        from fpl_agent.optimization.squad import build_player_pool_for_ids

        return build_player_pool_for_ids(conn, {pid}, event)[0]

    def make_move(o: int, i: int, gain: float) -> PlannedMove:
        out_c, in_c = candidate(o), candidate(i)
        next_xp(o), next_xp(i)
        out_ref = _ref(out_c, next_xp(o), starts, trends, solio, duties, match_xp)
        in_ref = _ref(in_c, next_xp(i), starts, trends, solio, duties, match_xp)
        timing, note = move_timing(out_ref, in_ref)
        return PlannedMove(
            out=out_ref, into=in_ref, gain=gain, cost_tenths=in_c.price_tenths - out_c.price_tenths,
            timing=timing, timing_note=note,
        )

    moves = [make_move(ordered_pairs[i], i, g) for _, i, g in accepted if i in ordered_pairs]
    if moves:
        try:
            stresses = stress_moves(solve, [(m.out.player_id, m.into.player_id) for m in moves], min_move_gain, event)
            moves = [replace(m, stress=st) for m, st in zip(moves, stresses, strict=True)]
        except Exception:
            _logger.exception("move stress test failed - the plan itself is unaffected")
    if moves:
        for idx, alts in enumerate(found_alternatives):
            slot = moves[idx]
            built = []
            for o, i, g in alts:
                a = make_move(o, i, g)
                # Same-position moves are interchangeable to the solver, so it pairs
                # them arbitrarily; an alternative into this slot sells this slot's player.
                if a.into.position == slot.into.position:
                    built.append(Alternative(
                        out=slot.out, into=a.into, gain=g, cost_tenths=a.into.price_tenths - slot.out.price_tenths,
                    ))
                else:
                    built.append(Alternative(out=a.out, into=a.into, gain=g, cost_tenths=a.cost_tenths))
            moves[idx] = replace(slot, alternatives=built)
    declined_moves = [make_move(o, i, g) for o, i, g in declined]

    xp_by_id = {pid: next_xp(pid) for pid in squad_ids}
    lineup_cache: dict = {}
    current_xi_ids = {c.player_id for c in locked.xi.starting}
    lineup_now = _lineup(conn, set(squad_ids), event, lineup_cache, starts, current_xi_ids)
    lineup_after = _lineup(conn, squad_after, event, lineup_cache, starts, current_xi_ids)
    as_set = _lineup_as_set(locked, xp_by_id, starts)

    out_ids = [m.out.player_id for m in moves]
    spent = sum(m.cost_tenths for m in moves)
    bank_after = bank - spent
    shortfall = _strict_sell_shortfall_tenths(conn, out_ids)
    if bank_after < 0:
        affordability = "Over budget at current prices - the plan is not affordable as built."
    elif bank_after - shortfall >= 0:
        affordability = "Affordable even if every sale raises only purchase price plus half the rise."
    else:
        affordability = (
            f"Affordable at current prices; if purchase prices are as recorded, sales raise up to "
            f"£{shortfall / 10:.1f}m less - check the FPL transfer screen before confirming."
        )

    road_ahead = None
    try:
        road_ahead = build_road_ahead(
            conn, squad_ids, free_transfers, bank, event, pool, cache, chosen_pairs, min_move_gain,
        )
    except Exception:
        _logger.exception("road-ahead solve failed - the plan for this week is unaffected")

    captain_ladder: list[dict] = []
    try:
        captain_ladder = build_captain_ladder(conn, squad_after, event, horizon, {})
    except Exception:
        _logger.exception("captain ladder failed - the plan itself is unaffected")

    team_outlook: dict = {}
    try:
        team_outlook = compact_team_outlook(conn, event)
    except Exception:
        _logger.exception("team outlook failed - the plan itself is unaffected")

    chip_outlook = build_chip_outlook(conn, event, sum(p.xp for p in lineup_after.bench))
    ft_after = min(free_transfers - min(len(moves), free_transfers) + 1, FREE_TRANSFER_CAP)
    notes: list[str] = []
    if not ft_known:
        notes.append("Free transfers could not be derived from synced history; one is assumed.")
    if free_transfers >= 5 and not moves:
        notes.append("Rolling at the cap discards a free transfer: next week you hold five either way.")

    return WeekPlan(
        event=event, horizon=horizon, free_transfers=free_transfers, free_transfers_known=ft_known,
        bank_tenths=bank, roll_total=round(roll_total, 2), plan_total=round(plan_total, 2),
        gain_vs_roll=round(plan_total - roll_total, 2), moves=moves, declined=declined_moves, curve=curve,
        ft_after=ft_after, bank_after_tenths=bank_after, affordability=affordability,
        lineup_now=lineup_now, lineup_after=lineup_after, lineup_set_by_you=as_set, road_ahead=road_ahead, chip_outlook=chip_outlook,
        solver={
            "proven_optimal": proven, "horizon": horizon, "pool_size": final.pool_size,
            "seconds": round(final.solve_seconds, 1), "min_move_gain": min_move_gain,
        },
        proven_optimal=proven, min_move_gain=min_move_gain, squad_ids=sorted(squad_ids),
        computed_at=datetime.now(timezone.utc).isoformat(), notes=notes, captain_ladder=captain_ladder,
        team_outlook=team_outlook,
    )


def week_plan_to_dict(plan: WeekPlan) -> dict:
    return asdict(plan)


def headline(plan: WeekPlan) -> str:
    if not plan.moves:
        return f"ROLL: nothing clears {plan.min_move_gain:g} points over {plan.horizon} gameweeks"
    return "; ".join(f"{m.out.name} -> {m.into.name}" for m in plan.moves)


def persist_week_plan(conn: sqlite3.Connection, plan: WeekPlan) -> int:
    return log_decision(
        conn, DECISION_TYPE, f"GW{plan.event}: {headline(plan)} ({plan.gain_vs_roll:+.1f} over {plan.horizon} GW)",
        week_plan_to_dict(plan), model_version="week-plan-v1",
        confidence="proven_optimal" if plan.proven_optimal else "best_found",
    )


def latest_week_plan(conn: sqlite3.Connection) -> tuple[dict, str, int] | None:
    decision = latest_decision_of_type(conn, DECISION_TYPE)
    if decision is None:
        return None
    return decision.detail, decision.created_at, decision.id


def light_squad_state(conn: sqlite3.Connection) -> dict | None:
    """The same squad, bank, free-transfer count and gameweek `get_locked_squad`
    reports, from plain reads. `get_locked_squad` also projects all fifteen
    players, which refits the team-strength model - seconds per call on a fresh
    connection - and a staleness check that runs on every page load cannot
    afford that."""
    from fpl_agent.ingestion.my_team import get_latest_squad_detail, get_my_team_entry_id
    from fpl_agent.models.free_transfers import compute_current_free_transfers

    entry_id = get_my_team_entry_id(conn)
    if entry_id is None:
        return None
    latest = get_latest_squad_detail(conn, entry_id)
    if latest is None:
        return None
    event, picks = latest
    summary = conn.execute(
        "SELECT bank_tenths FROM my_team_gw_summary WHERE entry_id=? AND event=?", (entry_id, event),
    ).fetchone()
    free_transfers = compute_current_free_transfers(conn, entry_id, upto_event=event)
    return {
        "event": event,
        "squad_ids": sorted(r["player_id"] for r in picks),
        "bank_tenths": int(round(summary["bank_tenths"] or 0)) if summary else 0,
        "free_transfers": free_transfers if free_transfers is not None else 1,
    }


REFRESH_AFTER_HOURS = 12
FINAL_DAY_REFRESH_HOURS = 6
FINAL_HALF_DAY_REFRESH_HOURS = 3


def refresh_after_hours(conn: sqlite3.Connection) -> float:
    """How old a stored plan may be before it is rebuilt. Twelve hours in the
    quiet middle of the week, six inside the last day and three inside the last
    twelve hours: team news, odds and predicted lineups all land close to the
    deadline, and the plan the manager acts on should have read them."""
    from fpl_agent.ingestion.odds_live_source import _hours_to_next_deadline

    hours = _hours_to_next_deadline(conn)
    if hours is not None and 0 < hours <= 12:
        return FINAL_HALF_DAY_REFRESH_HOURS
    if hours is not None and 0 < hours <= 24:
        return FINAL_DAY_REFRESH_HOURS
    return REFRESH_AFTER_HOURS


def _odds_newer_than(conn: sqlite3.Connection, created_at: str) -> bool:
    """A fresh bookmaker pull since the plan was made, inside the final day. The
    market reprices on team news, so it is the quickest read of it."""
    from fpl_agent.ingestion.odds_live_source import _hours_to_next_deadline

    hours = _hours_to_next_deadline(conn)
    if hours is None or not 0 < hours <= 24:
        return False
    row = conn.execute("SELECT value FROM app_meta WHERE key='odds_api_last_synced_at'").fetchone()
    if row is None:
        return False
    try:
        pulled = datetime.fromisoformat(row["value"].replace("Z", "+00:00"))
        made = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return pulled > made


def week_plan_staleness(conn: sqlite3.Connection, detail: dict, created_at: str) -> list[str]:
    """Why a stored plan no longer answers the question being asked; empty
    means it is current. A squad, bank, free-transfer count or target
    gameweek that differs from the plan's own inputs means the manager has
    moved since. A high-severity change to anyone the plan owns or targets
    means the world has."""
    from fpl_agent.models.decision_freshness import has_material_change_since

    reasons: list[str] = []
    state = light_squad_state(conn)
    if state is None:
        return ["no synced squad"]
    ids = state["squad_ids"]
    if ids != detail.get("squad_ids"):
        reasons.append("your squad has changed since this plan was made")
    if state["bank_tenths"] != detail.get("bank_tenths"):
        reasons.append("your bank has changed")
    if state["event"] + 1 != detail.get("event"):
        reasons.append("a new gameweek has started")
    if state["free_transfers"] != detail.get("free_transfers"):
        reasons.append("your free transfers have changed")
    watch = set(ids) | {m["into"]["player_id"] for m in detail.get("moves", [])} | {
        m["into"]["player_id"] for m in detail.get("declined", [])
    }
    change = has_material_change_since(conn, created_at, watch)
    if change is not None:
        name = conn.execute("SELECT web_name FROM players WHERE id=?", (change["entity_id"],)).fetchone()
        who = name["web_name"] if name and change["entity"] == "player" else f"{change['entity']} {change['entity_id']}"
        reasons.append(f"{who}: {change['event_type'].replace('_', ' ')} ({change['old_value']} to {change['new_value']})")
    return reasons


def _headline_from_detail(detail: dict) -> str:
    moves = detail.get("moves", [])
    return "; ".join(f"{m['out']['name']} -> {m['into']['name']}" for m in moves) or "ROLL"


def announce_plan_change(conn: sqlite3.Connection, previous: dict | None, plan: WeekPlan, reason: str) -> bool:
    """A new plan that makes different transfers from the last one for the same
    gameweek is worth a notification: it means something changed that the
    manager would want to know before the deadline. A rebuild that lands on the
    same moves is silent, as is the first plan of a gameweek. Recorded as a
    change event, so the alert engine's existing toast and the football wire
    carry it, and excluded from the staleness check so it can never make the
    plan it announces look out of date."""
    if previous is None or previous.get("event") != plan.event:
        return False
    old_moves = {(m["out"]["player_id"], m["into"]["player_id"]) for m in previous.get("moves", [])}
    new_moves = {(m.out.player_id, m.into.player_id) for m in plan.moves}
    if old_moves == new_moves:
        return False
    from fpl_agent.ingestion.change_detection import record_event

    record_event(
        conn, "week_plan_change", "plan", plan.event, _headline_from_detail(previous), headline(plan),
        datetime.now(timezone.utc).isoformat(), "week_plan", "model", "HIGH",
        fpl_impact=f"GW{plan.event} plan changed: {reason}",
    )
    conn.commit()
    return True


def refresh_week_plan_if_needed(conn: sqlite3.Connection) -> str | None:
    """Rebuilds and stores the plan when the stored one is missing, stale, or
    older than `REFRESH_AFTER_HOURS` (prices and fixtures drift even when
    nothing material is logged). Returns why it ran, or None when it did not.
    About twenty seconds of solver time, so it runs inline in the scheduled
    cycle rather than as a detached job."""
    stored = latest_week_plan(conn)
    reason: str | None = None
    if stored is None:
        reason = "no week plan has been made yet"
    else:
        detail, created_at, _ = stored
        reasons = week_plan_staleness(conn, detail, created_at)
        if reasons:
            reason = reasons[0]
        else:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            limit = refresh_after_hours(conn)
            if age.total_seconds() > limit * 3600:
                reason = f"the stored plan is {age.total_seconds() / 3600:.0f}h old"
            elif age.total_seconds() > 1800 and _odds_newer_than(conn, created_at):
                reason = "bookmaker odds were pulled after this plan was made"
    if reason is None:
        return None
    plan = build_week_plan(conn)
    if plan is None:
        return None
    persist_week_plan(conn, plan)
    try:
        announce_plan_change(conn, stored[0] if stored else None, plan, reason)
    except Exception:
        _logger.exception("could not record the plan change - the plan itself is saved")
    return reason


def dumps(plan: WeekPlan) -> str:
    return json.dumps(week_plan_to_dict(plan), default=str)
