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


def _candidates(conn: sqlite3.Connection, squad_ids: list[int], event: int | None = None):
    """`event` optionally evaluates a specific future gameweek instead of the
    default "next fixture from right now" - see expected_points()'s
    `from_event` docstring. Passing None (the default, what bench_boost_value/
    triple_captain_value/wildcard_value/freehit_value all still do) reproduces
    the exact prior behavior."""
    rows = conn.execute(
        f"SELECT p.id, p.web_name, et.singular_name_short AS position, p.team_id, t.short_name AS team_short "
        f"FROM players p JOIN element_types et ON et.id=p.element_type JOIN teams t ON t.id=p.team_id "
        f"WHERE p.id IN ({','.join('?' * len(squad_ids))})",
        squad_ids,
    ).fetchall()
    for r in rows:
        ep = expected_points(conn, r["id"], n_gw=1, from_event=event)
        yield PlayerCandidate(
            player_id=r["id"], web_name=r["web_name"], position=r["position"],
            team_id=r["team_id"], team_short=r["team_short"], price_tenths=0, xp=ep.median,
            median=ep.median, floor=ep.floor, ceiling=ep.ceiling, confidence=ep.confidence,
            expected_minutes=ep.expected_minutes,
        )


_squad_rebuild_cache: dict[tuple[int, int], tuple[object, object]] = {}


def _cached_optimise_squad(conn: sqlite3.Connection, n_gw: int):
    """Memoized optimise_squad - the rebuilt squad depends only on (conn, n_gw),
    never on squad_ids or event, but schedule_chips' DP calls the wildcard/freehit
    trial-value function once per (window, event) pair, which would otherwise
    re-run an identical ILP solve every time. Same module-level cache pattern
    models/expected_points.py::_get_or_fit_dc_model already uses for its own
    expensive fit; the stored conn is compared by identity so a recycled id()
    can't hand back another connection's result."""
    key = (id(conn), n_gw)
    cached = _squad_rebuild_cache.get(key)
    if cached is not None and cached[0] is conn:
        return cached[1]
    result = optimise_squad(conn, n_gw=n_gw)
    _squad_rebuild_cache[key] = (conn, result)
    return result


def _bench_boost_trial_values(
    conn: sqlite3.Connection, squad_ids: list[int], event: int, scenario_draw: list[ScenarioOutcome]
) -> np.ndarray:
    """Bench composition is a single deterministic pre-match choice (same
    pick_starting_xi call bench_boost_value already makes) - only the bench's
    realized points vary per scenario trial.

    The bench is picked from `event`-specific expected-points evaluation
    (_candidates(..., event=event), which threads through to
    expected_points()'s `from_event` - see CLAUDE.md's now-closed "chip
    selection is event-invariant" limitation), so a genuinely different
    bench can be picked for a genuinely different candidate gameweek, rather
    than always assuming today's bench."""
    squad = list(_candidates(conn, squad_ids, event=event))
    xi = pick_starting_xi(conn, squad)
    bench_ids = [c.player_id for c in xi.bench]
    return np.array([
        sum(o.points_by_event_player.get((event, pid), 0.0) for pid in bench_ids) for o in scenario_draw
    ])


def _triple_captain_trial_values(
    conn: sqlite3.Connection, squad_ids: list[int], event: int, scenario_draw: list[ScenarioOutcome]
) -> np.ndarray:
    """Extra points over a normal (2x) captaincy - one more multiple of the best
    option's realized points, mirroring triple_captain_value's median-based logic.

    The captain is picked from `event`-specific captaincy evaluation
    (evaluate_captaincy(..., event=event) - see CLAUDE.md's now-closed "chip
    selection is event-invariant" limitation), so a genuinely different
    captain can be picked for a genuinely different candidate gameweek,
    rather than always assuming today's captain."""
    options = evaluate_captaincy(conn, squad_ids, event=event)
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
    per trial, summed over the full horizon window.

    Every player scored here must be present in scenario_draw - the rebuilt squad
    comes from the FULL player pool, so it is generally not a subset of squad_ids.
    Callers are responsible for sampling the superset (see cli/main.py's
    season-sim); a missing player silently contributes 0.0 via the .get fallback."""
    rebuilt = _cached_optimise_squad(conn, horizon_gw)
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
class ChipExplanation:
    """Real "why now / why not later" narrative (2026-08-26, GW1-postmortem
    audit P1 "chip-strategy explanation") - built entirely from
    `window_event_median`, the same real per-(window, event) trial-median
    dict the DP itself already computes to make its choice, not a new
    heuristic. `best_alternative_event`/`best_alternative_value` name the
    real runner-up event within this chip's own real eligible window
    (`None` when there genuinely is no other real eligible event to compare
    against - an honest absence, not a fabricated one); `opportunity_cost`
    is the real, non-negative gap the DP's own choice already implies
    (never re-derived from a different metric)."""
    event: int
    chip_name: str
    expected_value: float
    best_alternative_event: int | None
    best_alternative_value: float | None
    opportunity_cost: float | None
    confidence: str  # "low" - same honesty posture as every other Monte-Carlo-trial-median output here


@dataclass(frozen=True)
class ChipSchedule:
    baseline_schedule: tuple[ChipScheduleEntry, ...]
    advisory_hit_recommendations: tuple[AdvisoryHitRecommendation, ...]
    # Sum of each scheduled window's own per-trial median - an approximation, NOT
    # the joint median of the summed trials (which would need the DP to carry
    # trial arrays rather than scalars).
    total_expected_value: float
    explanations: tuple[ChipExplanation, ...] = ()


def _squad_ids_by_event(initial_squad_ids: list[int], trajectory) -> dict[int, tuple[int, ...]]:
    current = list(initial_squad_ids)
    by_event = {}
    for step in trajectory.steps:
        if step.player_out_id is not None and step.player_in_id is not None:
            current = [step.player_in_id if pid == step.player_out_id else pid for pid in current]
        by_event[step.event] = tuple(current)
    return by_event


# Placeholder attribute (not a real top-level import - see _advisory_hit_recommendations'
# docstring for why) so tests can monkeypatch this module's best_transfer_for_player.
best_transfer_for_player = None


def _advisory_hit_recommendations(
    conn: sqlite3.Connection,
    initial_squad_ids: list[int],
    squad_trajectory,
    baseline_schedule: tuple[ChipScheduleEntry, ...],
    horizon_gw: int,
    scenario_draw: list[ScenarioOutcome],
) -> tuple[AdvisoryHitRecommendation, ...]:
    """For each baseline-scheduled chip event, tries whether an extra hit transfer
    right before it - a possibility Plan 1a's beam search structurally can't reach
    beyond horizon step 0, see CLAUDE.md's Pillar 1 Plan 1a section - would raise
    that chip's expected value. Scored against the SAME scenario_draw as the
    baseline (correlated comparison, not an independent redraw - see the Plan 1b
    design doc's Scenario reuse section). Advisory-only: never mutates
    squad_trajectory. Conservative bank_tenths=0 - see this task's docstring.

    best_transfer_for_player is referenced by its bare name rather than via a
    static top-level import: transfers.py already imports eligible_chips from
    this module, so a top-level `from ...transfers import
    best_transfer_for_player` here would be circular (and which side of the
    cycle loads first depends on which module a caller imports first). The
    module-level placeholder above keeps this module's own
    best_transfer_for_player attribute patchable by tests; the bare-name
    reference below resolves it via ordinary global lookup at call time, so a
    monkeypatched attribute is picked up automatically. The best_transfer_for_player
    deferred import only runs for real usage (when the attribute is still the
    placeholder), by which point both modules have finished loading. HIT_COST
    is imported the same deferred way, purely to dodge the same circularity,
    and is always fetched for real (it isn't monkeypatched by tests)."""
    from fpl_agent.optimization.transfers import HIT_COST

    transfer_fn = best_transfer_for_player
    if transfer_fn is None:
        from fpl_agent.optimization.transfers import best_transfer_for_player as transfer_fn

    squad_by_event = _squad_ids_by_event(initial_squad_ids, squad_trajectory)
    recommendations = []
    for entry in baseline_schedule:
        squad_ids = list(squad_by_event[entry.event])
        best_delta = 0.0
        best = None
        for player_out_id in squad_ids:
            for candidate in transfer_fn(
                conn, player_out_id, squad_ids, bank_tenths=0, is_hit=True, n_gw=1, top_n=1, from_event=entry.event,
            ):
                hypothetical_ids = [candidate.player_in_id if pid == player_out_id else pid for pid in squad_ids]
                fn = _TRIAL_VALUE_FUNCS[entry.chip_name]
                trial_values = fn(conn, hypothetical_ids, entry.event, horizon_gw, scenario_draw)
                advisory_value = float(np.median(trial_values)) - HIT_COST  # flat hit cost, same rule as transfers.py
                delta = advisory_value - entry.expected_marginal_value
                if delta > best_delta:
                    best_delta = delta
                    best = (player_out_id, candidate, advisory_value)
        if best is not None:
            player_out_id, candidate, advisory_value = best
            recommendations.append(
                AdvisoryHitRecommendation(
                    event=entry.event, chip_name=entry.chip_name,
                    player_out_id=player_out_id, player_out_name=candidate.player_out_name,
                    player_in_id=candidate.player_in_id, player_in_name=candidate.player_in_name,
                    baseline_expected_marginal_value=entry.expected_marginal_value,
                    advisory_expected_marginal_value=advisory_value,
                    delta=best_delta,
                )
            )
    return tuple(recommendations)


def _explain_schedule(
    entries: tuple[ChipScheduleEntry, ...],
    usable_windows: list["ChipWindow"],
    window_event_median: dict[tuple[int, int], float],
) -> tuple[ChipExplanation, ...]:
    name_to_index = {w.name: wi for wi, w in enumerate(usable_windows)}
    out = []
    for entry in entries:
        wi = name_to_index.get(entry.chip_name)
        alternatives = [
            (event, value) for (window_index, event), value in window_event_median.items()
            if window_index == wi and event != entry.event
        ]
        if alternatives:
            best_alt_event, best_alt_value = max(alternatives, key=lambda pair: pair[1])
            opportunity_cost = round(entry.expected_marginal_value - best_alt_value, 4)
        else:
            best_alt_event, best_alt_value, opportunity_cost = None, None, None
        out.append(ChipExplanation(
            event=entry.event, chip_name=entry.chip_name, expected_value=entry.expected_marginal_value,
            best_alternative_event=best_alt_event, best_alternative_value=best_alt_value,
            opportunity_cost=opportunity_cost, confidence="low",
        ))
    return tuple(out)


def schedule_chips(
    conn: sqlite3.Connection,
    initial_squad_ids: list[int],
    squad_trajectory,
    chip_windows: list[ChipWindow],
    scenario_draw: list[ScenarioOutcome],
    used_chip_names: set[str] = frozenset(),
) -> ChipSchedule:
    """DP over remaining chip_windows-eligible GWs, state = (used-window bitmask,
    event). Existing single-decision-point functions (bench_boost_value etc.) are
    untouched - this answers WHEN across the season, not is-it-worth-it this GW.
    Advisory hit-week reasoning (Task 7) is layered on top, never mutating this
    baseline's squad_trajectory.

    used_chip_names excludes chips already played this season from the DP state
    space. It has to be told, not inferred: there is no live FPL account
    integration in this project (a standing declined-scope decision), so nothing
    here can know what the user has already burned. Defaults to empty."""
    squad_by_event = _squad_ids_by_event(initial_squad_ids, squad_trajectory)
    if not squad_by_event:
        return ChipSchedule(baseline_schedule=(), advisory_hit_recommendations=(), total_expected_value=0.0)

    horizon_gw = len(squad_by_event)
    events = sorted(squad_by_event)
    usable_windows = [w for w in chip_windows if w.name in _TRIAL_VALUE_FUNCS and w.name not in used_chip_names]

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
    advisory = _advisory_hit_recommendations(conn, initial_squad_ids, squad_trajectory, best_entries, horizon_gw, scenario_draw)
    explanations = _explain_schedule(best_entries, usable_windows, window_event_median)
    return ChipSchedule(
        baseline_schedule=best_entries, advisory_hit_recommendations=advisory,
        total_expected_value=best_value, explanations=explanations,
    )
