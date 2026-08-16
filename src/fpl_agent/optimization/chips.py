"""
Chip optimiser (section 66). Deliberately scoped to two things:

1. Window eligibility - which of the 8 chip instances (2x each of wildcard/
   freehit/bench boost/triple captain) are usable in a given gameweek, straight
   from the official chip_windows table.
2. A single-decision-point heuristic value for each chip type, given the
   current squad and gameweek.

What this is NOT: season-long chip *scheduling* optimisation (picking the
single best gameweek across 38 to fire each chip, jointly with transfer
planning). That needs a real squad trajectory to optimise over, which doesn't
exist until a squad is actually built and played through some gameweeks -
revisit in a later phase once that exists, rather than building a stub that
pretends to plan the whole season now.
"""

import sqlite3
from dataclasses import dataclass
from typing import Callable

import numpy as np

from fpl_agent.models.expected_points import expected_points
from fpl_agent.models.fixtures import _reference_event
from fpl_agent.models.rules import current_season
from fpl_agent.models.scenario_engine import ScenarioOutcome
from fpl_agent.optimization.captaincy import evaluate_captaincy
from fpl_agent.optimization.squad import PlayerCandidate, optimise_squad, pick_starting_xi


@dataclass(frozen=True)
class ChipWindow:
    name: str
    number: int
    start_event: int
    stop_event: int
    chip_type: str
    eligible_now: bool


def eligible_chips(conn: sqlite3.Connection, event: int | None = None) -> list[ChipWindow]:
    event = event if event is not None else _reference_event(conn)
    season = current_season(conn)
    rows = conn.execute(
        "SELECT name, number, start_event, stop_event, chip_type FROM chip_windows "
        "WHERE season=? ORDER BY start_event",
        (season,),
    ).fetchall()
    return [
        ChipWindow(
            name=r["name"], number=r["number"], start_event=r["start_event"], stop_event=r["stop_event"],
            chip_type=r["chip_type"], eligible_now=r["start_event"] <= event <= r["stop_event"],
        )
        for r in rows
    ]


def bench_boost_value(conn: sqlite3.Connection, squad_ids: list[int]) -> float:
    squad = list(_candidates(conn, squad_ids))
    xi = pick_starting_xi(conn, squad)
    return round(sum(c.xp for c in xi.bench), 2)


def triple_captain_value(conn: sqlite3.Connection, squad_ids: list[int]) -> float:
    """Extra points over a normal (2x) captaincy - i.e. one more multiple of the best option's median."""
    options = evaluate_captaincy(conn, squad_ids)
    return round(options[0].median, 2) if options else 0.0


def wildcard_value(conn: sqlite3.Connection, squad_ids: list[int], n_gw: int = 5) -> float:
    """Projected xP gain from rebuilding the entire squad from scratch vs keeping it, over n_gw."""
    current_total = sum(expected_points(conn, pid, n_gw=n_gw).median for pid in squad_ids)
    rebuilt = optimise_squad(conn, n_gw=n_gw)
    return round(rebuilt.total_xp - current_total, 2)


def freehit_value(conn: sqlite3.Connection, squad_ids: list[int]) -> float:
    """Same idea as wildcard_value but single-GW - useful for spotting a blank/double week
    where a one-week-only rebuild clearly outscores the current squad."""
    return wildcard_value(conn, squad_ids, n_gw=1)


def _candidates(conn: sqlite3.Connection, squad_ids: list[int]):
    rows = conn.execute(
        f"SELECT p.id, p.web_name, et.singular_name_short AS position, p.team_id, t.short_name AS team_short "
        f"FROM players p JOIN element_types et ON et.id=p.element_type JOIN teams t ON t.id=p.team_id "
        f"WHERE p.id IN ({','.join('?' * len(squad_ids))})",
        squad_ids,
    ).fetchall()
    for r in rows:
        ep = expected_points(conn, r["id"], n_gw=1)
        yield PlayerCandidate(
            player_id=r["id"], web_name=r["web_name"], position=r["position"],
            team_id=r["team_id"], team_short=r["team_short"], price_tenths=0, xp=ep.median,
            median=ep.median, floor=ep.floor, ceiling=ep.ceiling, confidence=ep.confidence,
            expected_minutes=ep.expected_minutes,
        )


def _bench_boost_trial_values(
    conn: sqlite3.Connection, squad_ids: list[int], event: int, scenario_draw: list[ScenarioOutcome]
) -> np.ndarray:
    """Bench composition is a single deterministic pre-match choice (same
    pick_starting_xi call bench_boost_value already makes) - only the bench's
    realized points vary per scenario trial."""
    squad = list(_candidates(conn, squad_ids))
    xi = pick_starting_xi(conn, squad)
    bench_ids = [c.player_id for c in xi.bench]
    return np.array([
        sum(o.points_by_event_player.get((event, pid), 0.0) for pid in bench_ids) for o in scenario_draw
    ])


def _triple_captain_trial_values(
    conn: sqlite3.Connection, squad_ids: list[int], event: int, scenario_draw: list[ScenarioOutcome]
) -> np.ndarray:
    """Extra points over a normal (2x) captaincy - one more multiple of the best
    option's realized points, mirroring triple_captain_value's median-based logic."""
    options = evaluate_captaincy(conn, squad_ids)
    if not options:
        return np.zeros(len(scenario_draw))
    captain_id = options[0].player_id
    return np.array([o.points_by_event_player.get((event, captain_id), 0.0) for o in scenario_draw])


def _wildcard_trial_values(
    conn: sqlite3.Connection, squad_ids: list[int], event: int, horizon_gw: int, scenario_draw: list[ScenarioOutcome]
) -> np.ndarray:
    """The rebuilt squad is a single deterministic ILP solve (same optimise_squad
    call wildcard_value already makes - re-solving per trial would blow the runtime
    budget); only the realized-points GAP between it and the current squad varies
    per trial, summed over the full horizon window."""
    rebuilt = optimise_squad(conn, n_gw=horizon_gw)
    rebuilt_ids = [c.player_id for c in rebuilt.squad]
    events = range(event, event + horizon_gw)

    def _total(ids, outcome):
        return sum(outcome.points_by_event_player.get((e, pid), 0.0) for e in events for pid in ids)

    return np.array([_total(rebuilt_ids, o) - _total(squad_ids, o) for o in scenario_draw])


def _freehit_trial_values(
    conn: sqlite3.Connection, squad_ids: list[int], event: int, horizon_gw: int, scenario_draw: list[ScenarioOutcome]
) -> np.ndarray:
    """Same idea as _wildcard_trial_values but single-GW, mirroring freehit_value."""
    return _wildcard_trial_values(conn, squad_ids, event, 1, scenario_draw)


_TRIAL_VALUE_FUNCS: dict[str, Callable] = {
    "bboost": lambda conn, squad_ids, event, horizon_gw, scenario_draw: _bench_boost_trial_values(conn, squad_ids, event, scenario_draw),
    "3xc": lambda conn, squad_ids, event, horizon_gw, scenario_draw: _triple_captain_trial_values(conn, squad_ids, event, scenario_draw),
    "wildcard": _wildcard_trial_values,
    "freehit": _freehit_trial_values,
}


@dataclass(frozen=True)
class ChipScheduleEntry:
    event: int
    chip_name: str
    expected_marginal_value: float  # median across scenario_draw's trials


@dataclass(frozen=True)
class AdvisoryHitRecommendation:
    event: int
    chip_name: str
    player_out_id: int
    player_out_name: str
    player_in_id: int
    player_in_name: str
    baseline_expected_marginal_value: float
    advisory_expected_marginal_value: float
    delta: float


@dataclass(frozen=True)
class ChipSchedule:
    baseline_schedule: tuple[ChipScheduleEntry, ...]
    advisory_hit_recommendations: tuple[AdvisoryHitRecommendation, ...]
    total_expected_value: float


def _squad_ids_by_event(initial_squad_ids: list[int], trajectory) -> dict[int, tuple[int, ...]]:
    current = list(initial_squad_ids)
    by_event = {}
    for step in trajectory.steps:
        if step.player_out_id is not None and step.player_in_id is not None:
            current = [step.player_in_id if pid == step.player_out_id else pid for pid in current]
        by_event[step.event] = tuple(current)
    return by_event


def schedule_chips(
    conn: sqlite3.Connection,
    initial_squad_ids: list[int],
    squad_trajectory,
    chip_windows: list[ChipWindow],
    scenario_draw: list[ScenarioOutcome],
) -> ChipSchedule:
    """DP over remaining chip_windows-eligible GWs, state = (used-window bitmask,
    event). Existing single-decision-point functions (bench_boost_value etc.) are
    untouched - this answers WHEN across the season, not is-it-worth-it this GW.
    Advisory hit-week reasoning (Task 7) is layered on top, never mutating this
    baseline's squad_trajectory."""
    squad_by_event = _squad_ids_by_event(initial_squad_ids, squad_trajectory)
    if not squad_by_event:
        return ChipSchedule(baseline_schedule=(), advisory_hit_recommendations=(), total_expected_value=0.0)

    horizon_gw = len(squad_by_event)
    events = sorted(squad_by_event)
    usable_windows = [w for w in chip_windows if w.name in _TRIAL_VALUE_FUNCS]

    window_event_median: dict[tuple[int, int], float] = {}
    for wi, w in enumerate(usable_windows):
        for event in events:
            if not (w.start_event <= event <= w.stop_event):
                continue
            fn = _TRIAL_VALUE_FUNCS[w.name]
            trial_values = fn(conn, list(squad_by_event[event]), event, horizon_gw, scenario_draw)
            window_event_median[(wi, event)] = float(np.median(trial_values))

    dp: dict[int, tuple[float, tuple[ChipScheduleEntry, ...]]] = {0: (0.0, ())}
    for event in events:
        next_dp: dict[int, tuple[float, tuple[ChipScheduleEntry, ...]]] = {}
        for mask, (value, entries) in dp.items():
            if mask not in next_dp or next_dp[mask][0] < value:
                next_dp[mask] = (value, entries)
            for wi, w in enumerate(usable_windows):
                bit = 1 << wi
                if mask & bit:
                    continue
                marginal = window_event_median.get((wi, event))
                if marginal is None:
                    continue
                new_mask = mask | bit
                new_value = value + marginal
                if new_mask not in next_dp or next_dp[new_mask][0] < new_value:
                    entry = ChipScheduleEntry(event=event, chip_name=w.name, expected_marginal_value=marginal)
                    next_dp[new_mask] = (new_value, entries + (entry,))
        dp = next_dp

    best_mask = max(dp, key=lambda m: dp[m][0])
    best_value, best_entries = dp[best_mask]
    return ChipSchedule(baseline_schedule=best_entries, advisory_hit_recommendations=(), total_expected_value=best_value)
