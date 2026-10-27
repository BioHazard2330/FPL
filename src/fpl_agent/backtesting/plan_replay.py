"""The week plan's transfer policy replayed over a whole historical season, leakage-free.

`season_backtest.py` replays the old single-swap-or-roll rule. This replays the policy the week plan actually uses: the
exact multi-gameweek MILP (`milp_planner.plan_transfers_milp`) over a `HORIZON` window, free transfers banked up to the
cap of five, hits allowed when they pay, every transfer charged `BAR` points in the objective (the road-ahead form of the
week plan's per-move bar), and only the first gameweek's moves executed before re-planning next round. The policies start
from the same round-0 squad and are scored on the same real reconstructed points with the eleven and armband picked from
each round's projections:

- PLAN: the week plan's solver, every round of the horizon valued the same (one match at the player's projection);
- PLAN_COUNT: the same solver, each round valued by how many matches the club plays in it (blanks and doubles);
- PLAN_FIXTURE: as PLAN_COUNT, with each match's goals and assists scaled by the opponent and venue (see below);
- SWAP: one like-for-like transfer a round when it clears the old 2.0-point bar (`season_backtest`'s rule);
- HOLD: never transfer.

Fixture difficulty: at each decision a Dixon-Coles fit on results strictly before the round (`team_strength_dc`, live
half-life and ridge) gives every club's expected goals in each of its coming matches; a match is worth its expected goals
over the club's own average against this season's other clubs, so a player's rate (an average over mixed opponents) is
moved only by who and where he plays. Appearance and cards are not scaled. Values are divided by the season's mean
matches per club per round so all three PLAN variants sit on the same scale against `BAR`. The fixture list is the
season as played, so a rearranged match is known in advance (FPL announces most weeks ahead; some it does not).

Inputs are `season_backtest`'s: per-round projections from `harness.predict_player_round_points` (walk-forward, core
points only: appearance, goals, assists, cards), historical prices and clubs from the free archive. Disclosed limits, all
applied to every policy alike: no clean sheets, bonus or defensive points (so a defender's fixtures move only his
attacking returns); no chips; no auto-substitutes; sell price is the current price. A value from last season's points
(cold start, before a player has four matches) is not split, so it gets the match count but no difficulty. After
`COLD_START_ROUNDS` rounds a player with no in-season projection is out of the pool (see `_candidates`); a squad member
who drops out is valued at zero (every policy alike)."""
import math
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from fpl_agent.backtesting.harness import _round_start_dates, predict_player_round_parts
from fpl_agent.backtesting.season_backtest import (
    _TRANSFER_MATERIALITY_BAR,
    _best_single_transfer,
    _build_candidates,
    _build_initial_squad,
    _candidate_universe,
    _real_round_points,
)
from fpl_agent.ingestion.market_identity import normalize_common_team_name
from fpl_agent.models.team_strength_dc import expected_goals, fit_dixon_coles, load_matches_for_fitting
from fpl_agent.optimization.milp_planner import HIT_COST, plan_transfers_milp
from fpl_agent.optimization.squad import PlayerCandidate, pick_starting_xi

HORIZON = 5
BAR = 1.5
FT_CAP = 5
POOL_PER_POSITION = 20
SOLVE_SECONDS = 30
PLANS = ("plan", "plan_count", "plan_fixture")
CS_POINTS = {"GKP": 4, "DEF": 4, "MID": 1}
DEFAULT_CS = 0.25


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


def _candidates(conn, universe, season: str, round_start: str, i: int) -> tuple[list[PlayerCandidate], dict[int, tuple[float, float, float]]]:
    """`season_backtest._build_candidates`, except that once `COLD_START_ROUNDS` rounds have passed a player with no
    in-season projection (fewer than four matches this season) is not valued at last season's rate: he has not been
    playing, which the live minutes model sees and the replay's core projection does not. Also returns each in-season
    projection split as (appearance + cards, goals + assists, P(60+))."""
    import fpl_agent.backtesting.season_backtest as sb

    parts: dict[int, tuple[float, float, float]] = {}

    def recorded(c, pid, s, d, pos):
        p = predict_player_round_parts(c, pid, s, d, pos)
        if p is None:
            return None
        parts[pid] = p
        return p[0] + p[1]

    original_value, original_predict = sb._round_value, sb.predict_player_round_points
    sb.predict_player_round_points = recorded
    if i >= COLD_START_ROUNDS:
        sb._round_value = lambda c, pid, s, d, pos: recorded(c, pid, s, d, pos)
    try:
        return _build_candidates(conn, universe, season, round_start, "historical_gw", gw=i + 1)[0], parts
    finally:
        sb._round_value, sb.predict_player_round_points = original_value, original_predict


def _with_club_ids(candidates: list[PlayerCandidate]) -> list[PlayerCandidate]:
    """The MILP's three-per-club rule groups by `team_id`; the replay's clubs are the historical ones in `team_short`."""
    ids = {short: 10_000 + i for i, short in enumerate(sorted({c.team_short for c in candidates}))}
    return [PlayerCandidate(**{**c.__dict__, "team_id": ids[c.team_short]}) for c in candidates]


def _club_result_ids(conn, season: str) -> dict[str, int]:
    """Historical club code -> the club's id in `match_results_history`, by name through the shared normaliser."""
    played = {r[0] for r in conn.execute("SELECT home_team_id FROM match_results_history WHERE season=?", (season,))}
    out = {}
    for r in conn.execute("SELECT team_short_name, team_name FROM historical_team_strength WHERE season=?", (season,)):
        name = normalize_common_team_name(r[1])
        found = conn.execute(
            "SELECT id FROM market_teams WHERE canonical_name=? UNION SELECT market_team_id FROM team_name_aliases WHERE source_name=?",
            (name, name),
        ).fetchall()
        hits = {x[0] for x in found} & played
        if len(hits) == 1:
            out[r[0]] = hits.pop()
    return out


def _round_fixtures(conn, season: str, boundaries: list) -> list[list[tuple[int, int]]]:
    out = []
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        clause = "AND match_date < ?" if end else ""
        rows = conn.execute(
            f"SELECT home_team_id, away_team_id FROM match_results_history WHERE season=? AND match_date >= ? {clause}",
            (season, start) + ((end,) if end else ()),
        ).fetchall()
        out.append([(r[0], r[1]) for r in rows])
    return out


def fixture_ratios(
    conn, as_of: str, fixtures: list[list[tuple[int, int]]],
) -> tuple[list[dict[int, list[tuple[float, float]]]], dict[int, float]]:
    """Per round, per club: one (ratio, clean-sheet chance) per match. The ratio is the club's Dixon-Coles expected
    goals in it over its own average against the season's other clubs (home and away); the clean-sheet chance is
    exp(-opponent's expected goals), Poisson without the low-score correction. Also each club's average clean-sheet
    chance over the same opponents. (1.0, `DEFAULT_CS`) where either club is not in the fit."""
    clubs = {t for round_fx in fixtures for match in round_fx for t in match}
    matches, team_ids = load_matches_for_fitting(conn, as_of)
    model = None
    if len(matches) >= 20 and len(team_ids) >= 2:
        try:
            model = fit_dixon_coles(matches, team_ids)
        except RuntimeError:
            model = None
    known = {t for t in clubs if model is not None and t in model.teams}

    def scored(team: int, opponent: int, home: bool) -> float:
        return expected_goals(model, team, opponent)[0] if home else expected_goals(model, opponent, team)[1]

    def clean_sheet(team: int, opponent: int, home: bool) -> float:
        return math.exp(-scored(opponent, team, not home))

    pairs = {t: [(o, home) for o in known if o != t for home in (True, False)] for t in known} if len(known) > 1 else {}
    base = {t: statistics.fmean(scored(t, o, home) for o, home in pairs[t]) for t in pairs}
    base_cs = {t: statistics.fmean(clean_sheet(t, o, home) for o, home in pairs[t]) for t in pairs}
    out = []
    for round_fx in fixtures:
        per: dict[int, list[tuple[float, float]]] = defaultdict(list)
        for h, a in round_fx:
            for team, opponent, home in ((h, a, True), (a, h, False)):
                if team in base and opponent in known:
                    per[team].append((scored(team, opponent, home) / base[team], clean_sheet(team, opponent, home)))
                else:
                    per[team].append((1.0, DEFAULT_CS))
        out.append(per)
    return out, base_cs


def round_value(
    xp: float, parts: tuple[float, float, float] | None, cs_points: int, matches: list[tuple[float, float]] | None,
    base_cs: float, mean_matches: float, difficulty: bool,
) -> float:
    """A player's worth over one round. Each match is worth his projection plus P(60+) x clean-sheet points x the
    club's average clean-sheet chance; with `difficulty` the attacking part is scaled by the match's ratio and the
    match's own clean-sheet chance is used. Summed over his club's matches in the round and divided by the season's
    mean matches per club per round. `matches` None is one average match. A value from last season's points (`parts`
    None) already carries clean sheets and is only counted per match."""
    if parts is None:
        return xp if matches is None else xp * len(matches) / mean_matches
    steady, attack, p_full = parts
    cs_weight = p_full * cs_points
    if matches is None:
        return xp + cs_weight * base_cs
    if not difficulty:
        return (xp + cs_weight * base_cs) * len(matches) / mean_matches
    return sum(steady + attack * ratio + cs_weight * cs for ratio, cs in matches) / mean_matches


def _clean_sheet_points(conn, season: str, player: PlayerCandidate, round_start: str, round_end: str | None) -> int:
    """Clean-sheet points in the round: 60+ minutes in a match his club finished without conceding (FPL also gives
    them to a player subbed off after 60 before a late goal; counted as lost here)."""
    points = CS_POINTS.get(player.position, 0)
    if not points:
        return 0
    clause = "AND p.match_date < ?" if round_end else ""
    row = conn.execute(
        "SELECT COUNT(*) FROM player_match_stats_history p JOIN match_results_history m ON m.match_date = p.match_date "
        "AND (m.home_team_id = p.market_team_id OR m.away_team_id = p.market_team_id) "
        "WHERE p.season=? AND p.player_id=? AND p.minutes >= 60 AND p.match_date >= ? "
        f"AND (CASE WHEN m.home_team_id = p.market_team_id THEN m.away_goals ELSE m.home_goals END) = 0 {clause}",
        (season, player.player_id, round_start) + ((round_end,) if round_end else ()),
    ).fetchone()
    return points * row[0]


def _score(conn, season: str, squad: list[PlayerCandidate], round_start: str, round_end: str | None, unreliable: frozenset[int]) -> float:
    xi = pick_starting_xi(conn, squad)
    captain = xi.captain.player_id if xi.captain else None
    pts, _ = _real_round_points(conn, season, xi.starting, captain, round_start, round_end, unreliable)
    return pts + sum(
        _clean_sheet_points(conn, season, c, round_start, round_end) * (2 if c.player_id == captain else 1) for c in xi.starting
    )


def _plan_step(conn, run: PolicyRun, candidates: list[PlayerCandidate], by_id: dict, i: int, value) -> bool:
    """Plan the horizon with `value(candidate, round)` and execute the first round's moves; True if the solve was proven."""
    pool = candidates + [c for c in run.squad if c.player_id not in by_id]
    cache = {(c.player_id, i + 1 + k): value(c, i + k) for c in pool for k in range(HORIZON)}
    ranked = [PlayerCandidate(**{**c.__dict__, "xp": sum(cache[(c.player_id, i + 1 + k)] for k in range(HORIZON))}) for c in pool]
    result = plan_transfers_milp(
        conn, [c.player_id for c in run.squad], run.free_transfers, run.bank, start_event=i + 1,
        horizon_gw=HORIZON, pool_per_position=POOL_PER_POSITION, time_limit_seconds=SOLVE_SECONDS,
        model_chips=False, xp_cache=cache, league_pool=ranked, transfer_penalty=BAR,
    )
    used = 0
    proven = True
    if result.sequence is not None:
        proven = result.proven_optimal
        pool_by_id = {c.player_id: c for c in pool}
        for st in (st for st in result.sequence.steps if st.event == i + 1 and st.player_in_id is not None):
            out = next(c for c in run.squad if c.player_id == st.player_out_id)
            into = pool_by_id[st.player_in_id]
            run.bank += out.price_tenths - into.price_tenths
            run.squad = [into if c.player_id == out.player_id else c for c in run.squad]
            used += 1
        assert len({c.player_id for c in run.squad}) == 15
    hits = max(0, used - run.free_transfers)
    run.hits += hits
    run.points -= hits * HIT_COST
    run.transfers += used
    run.free_transfers = min(max(run.free_transfers - used, 0) + 1, FT_CAP)
    return proven


def run_plan_replay(conn: sqlite3.Connection, season: str, max_rounds: int | None = None) -> PlanReplayResult:
    from fpl_agent.backtesting.data_fidelity import MISSING_DATA, UNRESOLVED_ID, diagnose_season

    starts = _round_start_dates(conn, season)
    if not starts:
        raise ValueError(f"no rounds for {season}")
    boundaries = starts + [None]
    fixtures = _round_fixtures(conn, season, boundaries)
    clubs = {t for round_fx in fixtures for match in round_fx for t in match}
    mean_matches = 2 * sum(len(f) for f in fixtures) / (len(clubs) * len(fixtures))
    result_ids = _club_result_ids(conn, season)
    if max_rounds:
        starts = starts[:max_rounds]
    universe, _, _ = _candidate_universe(conn, season, "historical")
    round0, _, _ = _build_candidates(conn, universe, season, starts[0], "historical_gw", gw=1)
    squad0 = _build_initial_squad(round0)
    if squad0 is None:
        raise ValueError(f"round-0 squad infeasible for {season}")
    unreliable = frozenset(s.player_id for s in diagnose_season(conn, season) if s.derived_status in (MISSING_DATA, UNRESOLVED_ID))

    runs = {name: PolicyRun(name, list(squad0)) for name in (*PLANS, "swap", "hold")}
    per_round = []
    unproven = 0
    for i, round_start in enumerate(starts):
        round_end = boundaries[i + 1]
        candidates, parts = _candidates(conn, universe, season, round_start, i)
        candidates = _with_club_ids(candidates)
        by_id = {c.player_id: c for c in candidates}
        for run in runs.values():
            run.squad = [
                by_id.get(c.player_id) or (c if i < COLD_START_ROUNDS else PlayerCandidate(**{**c.__dict__, "xp": 0.0, "median": 0.0}))
                for c in run.squad
            ]
        ratios, base_cs = fixture_ratios(conn, round_start, fixtures)

        def value_for(count: bool, difficulty: bool):
            def value(c: PlayerCandidate, r: int) -> float:
                if not c.xp:
                    return 0.0
                club = result_ids.get(c.team_short)
                matches = ratios[r].get(club, []) if count and r < len(ratios) and club is not None else None
                return round_value(
                    c.xp, parts.get(c.player_id), CS_POINTS.get(c.position, 0), matches, base_cs.get(club, DEFAULT_CS),
                    mean_matches, difficulty,
                )
            return value

        flat = value_for(False, False)
        values = {"plan": flat, "plan_count": value_for(True, False), "plan_fixture": value_for(True, True)}

        if i > 0:
            for name in PLANS:
                unproven += 0 if _plan_step(conn, runs[name], candidates, by_id, i, values[name]) else 1

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
            value = values.get(name, flat)
            squad = [PlayerCandidate(**{**c.__dict__, "xp": value(c, i)}) for c in run.squad]
            pts = _score(conn, season, squad, round_start, round_end, unreliable)
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
