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

from fpl_agent.ingestion.lineup_probability_source import get_start_percent
from fpl_agent.models.expected_points import expected_points, expected_points_window
from fpl_agent.models.rules import current_season, get_rule
from fpl_agent.models.team_news_risk import rotation_risk_snippet

# Real, hard user directive (2026-08-21): "I dont want people in my squad
# that wont even start or has very rare chance to start. simple as is."
# Raised from 50 to 70 the same day, second real pushback: "hincapie doesnt
# have the greatest start either. 60% is too less, thats almost a coin
# flip. not possible." - 50% (a bare majority) wasn't a strong enough bar
# for the user's actual standard; 70% is a real, comfortably-above-coin-
# flip threshold, not just "more likely than not." Applies ONLY to what
# optimise_squad is allowed to SELECT for a brand-new squad - never to
# build_player_pool's other callers (rate_team.py rating an EXISTING
# squad, build_team.py's narrowly-missed list), which need the full,
# unfiltered pool to faithfully report on a squad someone already has or
# nearly missed rather than silently pretending a real player doesn't
# exist. must_include_ids (an explicit caller override) is exempt, same
# "the caller's own deliberate call" precedent optimise_squad's own
# docstring already establishes for that parameter.
_MIN_START_PERCENT_FOR_SQUAD = 70

# A bench player's real expected weekly contribution is far below a
# starter's - they only score when autosubbed in (a non-playing starter) or
# during a Bench Boost chip, both rare relative to "every week" a starter
# counts. 0.1 is a disclosed heuristic weight, not fit to real historical
# autosub-rate data (this project has none) - same honesty posture as
# price_forecast.py's threshold. Deliberately not 0.0: a bench player still
# has genuine optionality value (a real hedge against a starter blanking),
# just nowhere near a starter's.
_BENCH_WEIGHT = 0.1


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
    upside-oriented one (section 94's structure C). floor/ceiling/confidence/
    expected_minutes are always the single-next-match risk read (from
    expected_points(n_gw=1)) regardless of n_gw - a risk band and a playing-time
    estimate don't have a defined multi-gameweek meaning the way a point total does.

    `median`/`xp` (objective="median") come from expected_points_window(), the
    REAL cumulative sum across n_gw real fixtures - correctly sums a double
    gameweek, correctly zeroes a blank, rotation-damps each extra match. Fixed
    2026-08-21: n_gw previously flowed into expected_points()'s own n_gw, which
    only smooths ONE blended-difficulty snapshot over that many gameweeks of
    context (module docstring: "a window of context, not a multi-match total") -
    so `fpl build-squad --gw-window 5` was silently picking a squad off a single
    averaged-difficulty match, never off real summed value across 5 gameweeks,
    despite the flag's name. Same latent gap affected chips.py's wildcard/
    free-hit rebuild valuation (_cached_optimise_squad(conn, horizon_gw)) - now
    also correctly reflects real cumulative rebuild value over the horizon, not
    a smoothed one-match proxy. objective="ceiling" has no defined multi-gameweek
    meaning (expected_points_window only produces a median total) - raises
    ValueError if combined with n_gw>1 rather than silently falling back to a
    single-match ceiling while everything else in the pool is windowed."""
    if objective not in ("median", "ceiling"):
        raise ValueError(f"objective must be 'median' or 'ceiling', got {objective!r}")
    if objective == "ceiling" and n_gw > 1:
        raise ValueError("objective='ceiling' has no multi-gameweek window definition - use n_gw=1")

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
        ep = expected_points(conn, r["id"], n_gw=1)
        window_median = expected_points_window(conn, r["id"], n_gw=n_gw).total_median
        pool.append(
            PlayerCandidate(
                player_id=r["id"], web_name=r["web_name"], position=r["position"],
                team_id=r["team_id"], team_short=r["team_short"],
                price_tenths=price_row["value_tenths"],
                xp=ep.ceiling if objective == "ceiling" else window_median,
                median=window_median, floor=ep.floor, ceiling=ep.ceiling, confidence=ep.confidence,
                expected_minutes=ep.expected_minutes,
            )
        )
    return pool


def _low_start_confidence_ids(conn: sqlite3.Connection, candidate_ids: list[int]) -> set[int]:
    """Real ids a new squad must never include - a real start_percent below
    `_MIN_START_PERCENT_FOR_SQUAD` (ingestion/lineup_probability_source.py)
    OR a real rotation-risk keyword hit (models/team_news_risk.py) - EITHER
    signal excludes, not just whichever one happens to have data for a
    given player. Real, disclosed reason this is an OR rather than only
    consulting the keyword source as a fallback: the two sources
    demonstrably disagree for real players (Guehi: 97% per the percentage
    source, but fantasyfootballscout's own prose says "may have to miss out
    again" the same day) - caught live 2026-08-21 when the earlier
    percent-takes-precedence version still selected several squad members
    the keyword source had real hedge text for, directly contradicting the
    user's explicit "I dont want people in my squad that wont even start...
    simple as is." When two real sources disagree, exclude rather than
    trust the more optimistic one. A player covered by NEITHER source is
    still not excluded - absence of evidence isn't evidence of a real risk,
    same honesty posture the rest of this project's heuristics use."""
    excluded = set()
    for pid in candidate_ids:
        percent = get_start_percent(conn, pid)
        if percent is not None and percent < _MIN_START_PERCENT_FOR_SQUAD:
            excluded.add(pid)
            continue
        if rotation_risk_snippet(conn, pid) is not None:
            excluded.add(pid)
    return excluded


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
    bench_weight: float | None = None,
    must_include_ids: set[int] | None = None,
) -> SquadResult:
    """budget_override_tenths lets a caller solve under a tighter cap than the
    real rules budget (section 94's structure B: leaving bank spare for future
    flexibility) without touching the rules table.

    bench_weight overrides _BENCH_WEIGHT for this solve only (default: use the
    module constant) - a real, standing user preference (2026-08-20: "cant
    have 3 players on my bench as bench fodder, that wont make me able to
    rotate") that the default 0.1 weight structurally can't satisfy on its
    own, since it deliberately treats bench contribution as worth far less
    than a starter's. Raising it trades some starting-XI ceiling for genuine
    bench playability - the caller's call, not a silent default change.

    must_include_ids hard-locks specific players into the squad (e.g. "I want
    Haaland AND Fernandes regardless of cost-efficiency") - a real,
    disclosed override of pure EV-per-cost optimisation, not a bug: rank-
    variance/ownership-protection value on a near-mandatory premium asset is
    a legitimate reason a manager weighs differently than this optimiser's
    default objective does. Raises ValueError if a requested id isn't even
    in the position/exclude-filtered pool, rather than silently ignoring an
    impossible request."""
    season = current_season(conn)
    budget_tenths = budget_override_tenths if budget_override_tenths is not None else get_rule(
        conn, season, "rules.squad_total_spend", 1000
    )
    club_limit = get_rule(conn, season, "rules.squad_team_limit", 3)

    position_requirements = {
        r["singular_name_short"]: r["squad_select"]
        for r in conn.execute("SELECT singular_name_short, squad_select FROM element_types").fetchall()
    }
    play_bounds = {
        r["singular_name_short"]: (r["squad_min_play"], r["squad_max_play"])
        for r in conn.execute("SELECT singular_name_short, squad_min_play, squad_max_play FROM element_types").fetchall()
    }

    pool = build_player_pool(conn, n_gw=n_gw, exclude_ids=exclude_ids, objective=objective)
    if not pool:
        return SquadResult(squad=[], total_cost_tenths=0, total_xp=0.0, status="Infeasible (empty pool)")

    low_confidence_ids = _low_start_confidence_ids(conn, [c.player_id for c in pool])
    if must_include_ids:
        low_confidence_ids -= must_include_ids  # an explicit caller override still wins
    if low_confidence_ids:
        pool = [c for c in pool if c.player_id not in low_confidence_ids]
        if not pool:
            return SquadResult(
                squad=[], total_cost_tenths=0, total_xp=0.0,
                status="Infeasible (every remaining candidate has a real, unlikely-to-start signal)",
            )

    if must_include_ids:
        pool_ids = {c.player_id for c in pool}
        missing = must_include_ids - pool_ids
        if missing:
            raise ValueError(f"must_include_ids not in the candidate pool (excluded or unknown): {sorted(missing)}")

    weight = bench_weight if bench_weight is not None else _BENCH_WEIGHT

    prob = pulp.LpProblem("fpl_squad", pulp.LpMaximize)
    x = {c.player_id: pulp.LpVariable(f"x_{c.player_id}", cat="Binary") for c in pool}
    # Joint squad+XI+captain optimisation, not a plain Sum(xp) over all 15.
    # Two real-scoring facts a plain 15-man sum ignores: (1) captain doubles
    # points (section 65) - `cap` gives exactly one squad member one extra
    # copy of their own xp, same formulation public FPL optimiser tools use.
    # (2) only 11 of the 15 actually play most weeks - a bench player's real
    # expected contribution is near their FULL xp only on the rare week
    # they're autosubbed in or the squad plays Bench Boost, not every week
    # like a starter. Weighing all 15 equally (the pre-fix objective)
    # measurably mis-optimised for real GW score: confirmed live via
    # `fpl rate-team` on the real player pool, the old objective built a
    # squad that invested in a deep bench (~13.5 combined bench xp) instead
    # of Bruno Fernandes (6.23 xp, higher than every one of that squad's own
    # starters) purely because bench xp counted at full starter weight in
    # the objective, when it should barely count at all most weeks. `s`
    # marks the 11 starters (formation-bound the same way pick_starting_xi's
    # own min/max-play constraints already are, so the ILP's internal XI
    # choice and the actual reported XI agree); bench contribution
    # (`x - s`) is scaled by `_BENCH_WEIGHT`, a disclosed heuristic (not
    # fitted to real autosub-rate data, which this project doesn't have) -
    # not zero, since a bench player genuinely has some real optionality
    # value, just far below a starter's.
    s = {c.player_id: pulp.LpVariable(f"s_{c.player_id}", cat="Binary") for c in pool}
    cap = {c.player_id: pulp.LpVariable(f"cap_{c.player_id}", cat="Binary") for c in pool}

    prob += (
        pulp.lpSum(c.xp * s[c.player_id] for c in pool)
        + pulp.lpSum(c.xp * cap[c.player_id] for c in pool)
        + weight * pulp.lpSum(c.xp * (x[c.player_id] - s[c.player_id]) for c in pool)
    )
    prob += pulp.lpSum(cap[c.player_id] for c in pool) == 1
    prob += pulp.lpSum(s[c.player_id] for c in pool) == 11
    for c in pool:
        prob += cap[c.player_id] <= s[c.player_id]
        prob += s[c.player_id] <= x[c.player_id]
    prob += pulp.lpSum(c.price_tenths * x[c.player_id] for c in pool) <= budget_tenths

    for position, required in position_requirements.items():
        prob += pulp.lpSum(x[c.player_id] for c in pool if c.position == position) == required
        min_play, max_play = play_bounds.get(position, (0, 11))
        starters_in_position = pulp.lpSum(s[c.player_id] for c in pool if c.position == position)
        prob += starters_in_position >= min_play
        prob += starters_in_position <= max_play

    for team_id in {c.team_id for c in pool}:
        prob += pulp.lpSum(x[c.player_id] for c in pool if c.team_id == team_id) <= club_limit

    for pid in must_include_ids or ():
        prob += x[pid] == 1

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


def validate_starting_xi(xi: StartingXI) -> list[str]:
    """Real, explicit validation gate (2026-08-21, locked-squad product
    architecture pass) - a rendering caller must check this and refuse to
    render rather than silently show a broken pitch. Returns a list of
    human-readable problems, empty when the XI is genuinely valid. Checked
    directly against `optimise_squad`/`pick_starting_xi`/`rate_team`'s own
    real code paths this session and could not reproduce a duplicate-player
    state live - `rate_team.py::rate_team` already carries its own
    deduplication fix for a related historical incident (see its own
    docstring) - this is a permanent safety net regardless of root cause,
    not a patch for a reproduced bug."""
    problems: list[str] = []
    all_ids = [c.player_id for c in xi.starting] + [c.player_id for c in xi.bench]
    seen: set[int] = set()
    duplicates: set[int] = set()
    for pid in all_ids:
        if pid in seen:
            duplicates.add(pid)
        seen.add(pid)
    if duplicates:
        problems.append(f"player(s) appear in both starting XI and bench: {sorted(duplicates)}")
    if len(xi.starting) > 11:
        problems.append(f"starting XI has {len(xi.starting)} players, expected at most 11")
    if xi.captain is not None and xi.captain.player_id not in {c.player_id for c in xi.starting}:
        problems.append(f"captain ({xi.captain.web_name}) is not in the starting XI")
    if xi.vice_captain is not None and xi.vice_captain.player_id not in {c.player_id for c in xi.starting}:
        problems.append(f"vice-captain ({xi.vice_captain.web_name}) is not in the starting XI")
    return problems


def pick_starting_xi(
    conn: sqlite3.Connection, squad: list[PlayerCandidate], must_start_ids: set[int] | None = None,
) -> StartingXI:
    """Best valid XI from an already-chosen 15. Small search space (15 players,
    4 positions) - greedy-by-xP within each position's min/max play bounds,
    then fill remaining slots up to 11 by best xP regardless of position.

    `must_start_ids` (2026-08-21) - real, explicit override: `optimise_squad`'s
    own `must_include_ids` only guarantees SQUAD membership, not a starting
    spot (real gap found live - a forced-in player with a thin real per-90
    track record, e.g. a promising but unproven signing, still lost the XI
    place to established starters on pure median, even on an easy fixture -
    the user's real, explicit intent was for them to actually START, not
    just make the 15). Forced starters are placed FIRST, before the greedy
    min-play fill, same "caller's own deliberate call" precedent
    `optimise_squad`'s `must_include_ids` already established. Silently
    skips a forced id if the formation genuinely has no room left at their
    position (e.g. two forced GKPs) rather than raising - same graceful-
    limit handling the existing min-play fill already uses."""
    must_start_ids = must_start_ids or set()
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
    for c in squad:
        if c.player_id not in must_start_ids or len(starting) >= 11:
            continue
        pos_max = play_bounds.get(c.position, (0, 11))[1]
        pos_count = sum(1 for s in starting if s.position == c.position)
        if pos_count < pos_max:
            starting.append(c)

    for position, (min_play, _max_play) in play_bounds.items():
        pos_count = sum(1 for s in starting if s.position == position)
        needed = max(min_play - pos_count, 0)
        for c in by_position.get(position, []):
            if needed <= 0 or len(starting) >= 11:
                break
            if c in starting:
                continue
            starting.append(c)
            needed -= 1

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
