"""
Squad optimiser (section 61). A 15-man FPL squad under budget/position/club-limit
constraints is a constrained knapsack problem - solved exactly with a MILP (PuLP +
bundled CBC) rather than a greedy heuristic, which can miss the true optimum when
budget is tight enough that swapping a cheap-but-weak player for a slightly pricier
strong one elsewhere requires downgrading a third player to stay in budget.
"""

import sqlite3
from dataclasses import dataclass, field

import pulp

from fpl_agent.models.expected_points import expected_points
from fpl_agent.models.rules import current_season, get_rule


@dataclass(frozen=True)
class PlayerCandidate:
    player_id: int
    web_name: str
    position: str
    team_id: int
    team_short: str
    price_tenths: int
    xp: float          # the objective value actually optimised (median or ceiling)
    median: float
    floor: float
    ceiling: float
    confidence: str
    expected_minutes: float


def build_player_pool(
    conn: sqlite3.Connection, n_gw: int = 1, exclude_ids: set[int] | None = None, objective: str = "median"
) -> list[PlayerCandidate]:
    """objective picks which ExpectedPoints field becomes `xp` (the value the
    optimiser maximises) - "median" for a best-EV squad, "ceiling" for a
    upside-oriented one (section 94's structure C). floor/median/ceiling/confidence
    are always carried through regardless, so callers can inspect risk either way."""
    if objective not in ("median", "ceiling"):
        raise ValueError(f"objective must be 'median' or 'ceiling', got {objective!r}")

    exclude_ids = exclude_ids or set()
    rows = conn.execute(
        "SELECT p.id, p.web_name, et.singular_name_short AS position, p.team_id, t.short_name AS team_short "
        "FROM players p "
        "JOIN element_types et ON et.id = p.element_type "
        "JOIN teams t ON t.id = p.team_id "
        "WHERE p.removed = 0"
    ).fetchall()

    pool = []
    for r in rows:
        if r["id"] in exclude_ids:
            continue
        price_row = conn.execute(
            "SELECT value_tenths FROM player_price_history WHERE player_id=? AND valid_until IS NULL",
            (r["id"],),
        ).fetchone()
        if price_row is None:
            continue
        ep = expected_points(conn, r["id"], n_gw=n_gw)
        pool.append(
            PlayerCandidate(
                player_id=r["id"], web_name=r["web_name"], position=r["position"],
                team_id=r["team_id"], team_short=r["team_short"],
                price_tenths=price_row["value_tenths"],
                xp=ep.ceiling if objective == "ceiling" else ep.median,
                median=ep.median, floor=ep.floor, ceiling=ep.ceiling, confidence=ep.confidence,
                expected_minutes=ep.expected_minutes,
            )
        )
    return pool


@dataclass(frozen=True)
class SquadResult:
    squad: list[PlayerCandidate]
    total_cost_tenths: int
    total_xp: float
    status: str


def optimise_squad(
    conn: sqlite3.Connection,
    n_gw: int = 1,
    exclude_ids: set[int] | None = None,
    objective: str = "median",
    budget_override_tenths: int | None = None,
) -> SquadResult:
    """budget_override_tenths lets a caller solve under a tighter cap than the
    real rules budget (section 94's structure B: leaving bank spare for future
    flexibility) without touching the rules table."""
    season = current_season(conn)
    budget_tenths = budget_override_tenths if budget_override_tenths is not None else get_rule(
        conn, season, "rules.squad_total_spend", 1000
    )
    club_limit = get_rule(conn, season, "rules.squad_team_limit", 3)

    position_requirements = {
        r["singular_name_short"]: r["squad_select"]
        for r in conn.execute("SELECT singular_name_short, squad_select FROM element_types").fetchall()
    }

    pool = build_player_pool(conn, n_gw=n_gw, exclude_ids=exclude_ids, objective=objective)
    if not pool:
        return SquadResult(squad=[], total_cost_tenths=0, total_xp=0.0, status="Infeasible (empty pool)")

    prob = pulp.LpProblem("fpl_squad", pulp.LpMaximize)
    x = {c.player_id: pulp.LpVariable(f"x_{c.player_id}", cat="Binary") for c in pool}

    prob += pulp.lpSum(c.xp * x[c.player_id] for c in pool)
    prob += pulp.lpSum(c.price_tenths * x[c.player_id] for c in pool) <= budget_tenths

    for position, required in position_requirements.items():
        prob += pulp.lpSum(x[c.player_id] for c in pool if c.position == position) == required

    for team_id in {c.team_id for c in pool}:
        prob += pulp.lpSum(x[c.player_id] for c in pool if c.team_id == team_id) <= club_limit

    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    status = pulp.LpStatus[prob.status]

    if status != "Optimal":
        return SquadResult(squad=[], total_cost_tenths=0, total_xp=0.0, status=status)

    squad = [c for c in pool if x[c.player_id].value() == 1]
    return SquadResult(
        squad=squad,
        total_cost_tenths=sum(c.price_tenths for c in squad),
        total_xp=round(sum(c.xp for c in squad), 2),
        status=status,
    )


@dataclass(frozen=True)
class StartingXI:
    starting: list[PlayerCandidate]
    bench: list[PlayerCandidate] = field(default_factory=list)
    captain: PlayerCandidate | None = None
    vice_captain: PlayerCandidate | None = None


def pick_starting_xi(conn: sqlite3.Connection, squad: list[PlayerCandidate]) -> StartingXI:
    """Best valid XI from an already-chosen 15. Small search space (15 players,
    4 positions) - greedy-by-xP within each position's min/max play bounds,
    then fill remaining slots up to 11 by best xP regardless of position."""
    play_bounds = {
        r["singular_name_short"]: (r["squad_min_play"], r["squad_max_play"])
        for r in conn.execute("SELECT singular_name_short, squad_min_play, squad_max_play FROM element_types").fetchall()
    }

    by_position: dict[str, list[PlayerCandidate]] = {}
    for c in squad:
        by_position.setdefault(c.position, []).append(c)
    for players in by_position.values():
        players.sort(key=lambda c: c.xp, reverse=True)

    starting: list[PlayerCandidate] = []
    for position, (min_play, _max_play) in play_bounds.items():
        starting.extend(by_position.get(position, [])[:min_play])

    remaining = sorted(
        (c for c in squad if c not in starting),
        key=lambda c: c.xp, reverse=True,
    )
    for c in remaining:
        if len(starting) >= 11:
            break
        pos_max = play_bounds.get(c.position, (0, 11))[1]
        pos_count = sum(1 for s in starting if s.position == c.position)
        if pos_count < pos_max:
            starting.append(c)

    starting.sort(key=lambda c: c.xp, reverse=True)
    bench = sorted((c for c in squad if c not in starting), key=lambda c: c.xp, reverse=True)

    captain = starting[0] if starting else None
    vice_captain = starting[1] if len(starting) > 1 else None

    return StartingXI(starting=starting, bench=bench, captain=captain, vice_captain=vice_captain)
