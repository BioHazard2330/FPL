"""
BUILD MY FIRST TEAM orchestrator (section 92-94). Wires together the squad
optimiser, captaincy, availability, differentials/breakouts, and change events
into the section 93 output shape. Three structures (section 94): A - best EV,
B - best flexibility (tighter budget cap, leaves bank spare), C - best upside
(ceiling objective) - each a genuinely different optimiser run, not relabeled
copies of the same result.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from fpl_agent.models.availability import list_availability
from fpl_agent.models.breakouts import find_breakouts
from fpl_agent.models.rules import current_season, get_rule
from fpl_agent.optimization.captaincy import CaptainOption, captaincy_report
from fpl_agent.optimization.squad import (
    PlayerCandidate,
    SquadResult,
    StartingXI,
    build_player_pool,
    optimise_squad,
    pick_starting_xi,
)

FLEXIBILITY_BUDGET_FRACTION = 0.97  # structure B leaves ~3% of budget as bank


@dataclass(frozen=True)
class AlternativeSquad:
    label: str
    result: SquadResult
    xi: StartingXI


@dataclass(frozen=True)
class BuildTeamReport:
    structures: list[AlternativeSquad]  # [A, B, C]
    captain: CaptainOption | None
    vice: CaptainOption | None
    risks: list[str]
    narrowly_missed: list[PlayerCandidate]
    watchlist: list[str]
    retrieved_at: str


def _narrowly_missed(conn: sqlite3.Connection, selected_ids: set[int]) -> list[PlayerCandidate]:
    pool = build_player_pool(conn, n_gw=1, objective="median")
    by_position: dict[str, list[PlayerCandidate]] = {}
    for c in pool:
        by_position.setdefault(c.position, []).append(c)

    missed = []
    for players in by_position.values():
        players.sort(key=lambda c: c.xp, reverse=True)
        for c in players:
            if c.player_id not in selected_ids:
                missed.append(c)
                break
    return missed


def _watchlist(conn: sqlite3.Connection, selected_ids: set[int]) -> list[str]:
    items = []
    new_players = conn.execute(
        "SELECT entity_id FROM change_events WHERE event_type='new_player' ORDER BY detected_at DESC LIMIT 5"
    ).fetchall()
    for row in new_players:
        p = conn.execute("SELECT web_name FROM players WHERE id=?", (row["entity_id"],)).fetchone()
        if p:
            items.append(f"new player: {p['web_name']}")

    for b in find_breakouts(conn)[:3]:
        if b.player_id not in selected_ids:
            items.append(f"breakout watch: {b.web_name} ({', '.join(b.reasons)})")

    return items


def generate_build_team_report(conn: sqlite3.Connection) -> BuildTeamReport:
    season = current_season(conn)
    budget_tenths = get_rule(conn, season, "rules.squad_total_spend", 1000)

    result_a = optimise_squad(conn, n_gw=1, objective="median")
    xi_a = pick_starting_xi(conn, result_a.squad)

    result_b = optimise_squad(conn, n_gw=1, budget_override_tenths=int(budget_tenths * FLEXIBILITY_BUDGET_FRACTION))
    xi_b = pick_starting_xi(conn, result_b.squad)

    result_c = optimise_squad(conn, n_gw=1, objective="ceiling")
    xi_c = pick_starting_xi(conn, result_c.squad)

    squad_ids_a = {c.player_id for c in result_a.squad}

    cap_report = captaincy_report(conn, list(squad_ids_a)) if result_a.squad else None

    availability = list_availability(conn, unavailable_only=True)
    risks = [f"{a.web_name}: {a.classification}" for a in availability if a.player_id in squad_ids_a]

    return BuildTeamReport(
        structures=[
            AlternativeSquad("A - Best expected value", result_a, xi_a),
            AlternativeSquad("B - Best flexibility", result_b, xi_b),
            AlternativeSquad("C - Best calculated upside", result_c, xi_c),
        ],
        captain=cap_report.best if cap_report else None,
        vice=cap_report.second if cap_report else None,
        risks=risks,
        narrowly_missed=_narrowly_missed(conn, squad_ids_a),
        watchlist=_watchlist(conn, squad_ids_a),
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )
