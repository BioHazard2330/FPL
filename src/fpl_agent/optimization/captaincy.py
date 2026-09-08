"""
Captaincy optimiser (section 65). Ranks a given squad's next-fixture options by
median xP, ceiling, floor, fixture, set-piece role, and rotation risk. Surfaces
sampled effective ownership (Plan 1c) when available - real rank-differential
armband opportunities, not just popular picks.
"""

import sqlite3
from dataclasses import dataclass

from fpl_agent.models.effective_ownership import get_all_sample_eo
from fpl_agent.models.expected_points import ComponentBreakdown, expected_points
from fpl_agent.models.fixtures import _reference_event


@dataclass(frozen=True)
class CaptainOption:
    player_id: int
    web_name: str
    position: str
    floor: float
    median: float
    ceiling: float
    confidence: str
    expected_minutes: float
    is_penalty_taker: bool
    opponent_short: str | None
    is_home: bool | None
    selected_by_percent: float | None
    effective_ownership_percent: float | None
    eo_source: str  # "sampled" or "unavailable"
    # Real per-component xP decomposition (2026-09-07, Phase 7.3 Part 13 -
    # "show the primary reason [for this captain pick], not merely
    # 'Haaland 5.3 xP'") - the SAME `ExpectedPoints.components` every other
    # consumer already reads, never a second, independently-computed
    # breakdown. See `captain_edge_driver`'s own docstring for how this
    # becomes a real, evidence-grounded "why" rather than a bare number.
    components: "ComponentBreakdown | None" = None
    # Real team identity (2026-09-08, art-direction pass v3) - lets a JSON
    # payload consumer (the React COMMAND screen's captain battle) resolve a
    # real shirt/crest without a fragile cross-reference into a differently-
    # scoped payload block. Defaulted so every pre-existing test fixture
    # that builds a CaptainOption without it keeps working unchanged.
    team_id: int = 0


def _next_opponent(conn: sqlite3.Connection, team_id: int, event: int | None = None) -> tuple[str | None, bool | None]:
    event = event if event is not None else _reference_event(conn)
    fixture = conn.execute(
        "SELECT team_h, team_a FROM fixtures WHERE (team_h=? OR team_a=?) AND event=? LIMIT 1",
        (team_id, team_id, event),
    ).fetchone()
    if fixture is None:
        return None, None
    is_home = fixture["team_h"] == team_id
    opponent_id = fixture["team_a"] if is_home else fixture["team_h"]
    opponent = conn.execute("SELECT short_name FROM teams WHERE id=?", (opponent_id,)).fetchone()
    return (opponent["short_name"] if opponent else None), is_home


def _is_penalty_taker(conn: sqlite3.Connection, player_id: int) -> bool:
    row = conn.execute(
        "SELECT penalties_order FROM player_setpiece_history WHERE player_id=? AND valid_until IS NULL",
        (player_id,),
    ).fetchone()
    return bool(row and row["penalties_order"] == 1)


def evaluate_captaincy(conn: sqlite3.Connection, squad_ids: list[int], event: int | None = None) -> list[CaptainOption]:
    """`event` optionally evaluates a specific future gameweek instead of the
    default "next fixture from right now" - see expected_points()'s
    `from_event` docstring. Passing None (the default) reproduces the exact
    prior behavior."""
    eo_by_player = get_all_sample_eo(conn)
    options = []
    for player_id in squad_ids:
        ep = expected_points(conn, player_id, n_gw=1, from_event=event)
        player = conn.execute(
            "SELECT web_name, team_id, selected_by_percent FROM players p "
            "LEFT JOIN player_ownership_history oh ON oh.player_id = p.id AND oh.valid_until IS NULL "
            "WHERE p.id=?",
            (player_id,),
        ).fetchone()
        opponent, is_home = _next_opponent(conn, player["team_id"], event)

        # Absent from a non-empty sample means "no measurement was taken for this
        # player", not a measured zero - ~750 sampled managers can't cover every player.
        # Captaincy has no raw-ownership fallback to report as EO, so an unmeasured
        # player is "unavailable" (same as when no sample exists at all), which also
        # keeps differential_captain_note from firing off a fabricated 0.0%.
        eo = eo_by_player.get(player_id)
        eo_percent = eo.eo_percent if eo is not None else None
        eo_source = "sampled" if eo is not None else "unavailable"

        options.append(
            CaptainOption(
                player_id=player_id, web_name=player["web_name"], position=ep.position,
                team_id=player["team_id"],
                floor=ep.floor, median=ep.median, ceiling=ep.ceiling, confidence=ep.confidence,
                expected_minutes=ep.expected_minutes,
                is_penalty_taker=_is_penalty_taker(conn, player_id),
                opponent_short=opponent, is_home=is_home,
                selected_by_percent=player["selected_by_percent"],
                effective_ownership_percent=eo_percent, eo_source=eo_source,
                components=ep.components,
            )
        )
    options.sort(key=lambda o: o.median, reverse=True)
    return options


_COMPONENT_LABELS = {
    "appearance": "minutes",
    "goals": "goal probability",
    "assists": "assist probability",
    "clean_sheet": "fixture (defence)",
    "conceded": "fixture (defence)",
    "bonus": "match involvement",
    "defcon": "defensive actions",
    "cards": "card risk",
}


def captain_edge_driver(current: CaptainOption, alternative: CaptainOption) -> tuple[str, float] | None:
    """Real, evidence-grounded "why does the model prefer this captain"
    (2026-09-07, Phase 7.3 Part 13) - a valid counterfactual read, not a
    manufactured additive decomposition (see Part 11's own "only expose
    contribution metrics that are mathematically defensible"): the single
    `ComponentBreakdown` field with the largest real per-90-equivalent
    magnitude difference between the two players' own already-computed
    projections. `None` when either side has no `components` (the honest
    "not computable" case, e.g. a blank-gameweek fallback projection - see
    `ExpectedPoints.components`'s own docstring), never a fabricated driver.

    This is a real DIFFERENCE-of-components read, not a decomposition of the
    gap into parts that sum to it - two players' components don't isolate a
    single edge value the way a counterfactual remove/recompute would (that
    would mean re-running `expected_points` with one component forced to the
    other player's value, a real but substantially heavier computation this
    function deliberately does not attempt) - it answers "which single real
    factor differs most between these two projections", which is what
    "primary reason: fixture / goal probability / assist probability /
    minutes" (spec) actually asks for."""
    if current.components is None or alternative.components is None:
        return None
    fields = ("appearance", "goals", "assists", "clean_sheet", "conceded", "bonus", "defcon", "cards")
    deltas = {f: getattr(current.components, f) - getattr(alternative.components, f) for f in fields}
    driver_field = max(deltas, key=lambda f: abs(deltas[f]))
    return _COMPONENT_LABELS[driver_field], round(deltas[driver_field], 2)


@dataclass(frozen=True)
class CaptaincyReport:
    best: CaptainOption | None
    second: CaptainOption | None
    safe: CaptainOption | None
    high_upside: CaptainOption | None
    risks: list[str]
    differential_captain_note: str | None = None


def captaincy_report(conn: sqlite3.Connection, squad_ids: list[int]) -> CaptaincyReport:
    options = evaluate_captaincy(conn, squad_ids)
    if not options:
        return CaptaincyReport(None, None, None, None, [], None)

    best = options[0]
    second = options[1] if len(options) > 1 else None
    safe = max(options, key=lambda o: o.floor)
    high_upside = max(options, key=lambda o: o.ceiling)

    risks = []
    for o in options[:3]:
        if o.confidence == "LOW":
            risks.append(f"{o.web_name}: LOW confidence (limited current-season data)")
        if o.expected_minutes < 75:
            risks.append(f"{o.web_name}: rotation/minutes risk (expected {o.expected_minutes:.0f} mins)")
        if o.opponent_short is None:
            risks.append(f"{o.web_name}: no fixture found in the reference gameweek (blank?)")

    differential_captain_note = None
    if (
        best.eo_source == "sampled"
        and best.selected_by_percent is not None
        and best.selected_by_percent > 0
        and best.effective_ownership_percent < 0.5 * best.selected_by_percent
    ):
        differential_captain_note = (
            f"{best.web_name}: field owns {best.selected_by_percent:.1f}% but only "
            f"{best.effective_ownership_percent:.1f}% effective ownership - captaining your best pick "
            f"is a real rank differential, not just a popular pick"
        )

    return CaptaincyReport(
        best=best, second=second, safe=safe, high_upside=high_upside, risks=risks,
        differential_captain_note=differential_captain_note,
    )
