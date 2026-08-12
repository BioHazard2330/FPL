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

from fpl_agent.models.expected_points import expected_points
from fpl_agent.models.fixtures import _reference_event
from fpl_agent.models.rules import current_season
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
