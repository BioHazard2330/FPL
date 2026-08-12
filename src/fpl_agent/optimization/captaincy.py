"""
Captaincy optimiser (section 65). Ranks a given squad's next-fixture options by
median xP, ceiling, floor, fixture, set-piece role, and rotation risk.
"""

import sqlite3
from dataclasses import dataclass

from fpl_agent.models.expected_points import expected_points
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


def _next_opponent(conn: sqlite3.Connection, team_id: int) -> tuple[str | None, bool | None]:
    event = _reference_event(conn)
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


def evaluate_captaincy(conn: sqlite3.Connection, squad_ids: list[int]) -> list[CaptainOption]:
    options = []
    for player_id in squad_ids:
        ep = expected_points(conn, player_id, n_gw=1)
        player = conn.execute(
            "SELECT web_name, team_id, selected_by_percent FROM players p "
            "LEFT JOIN player_ownership_history oh ON oh.player_id = p.id AND oh.valid_until IS NULL "
            "WHERE p.id=?",
            (player_id,),
        ).fetchone()
        opponent, is_home = _next_opponent(conn, player["team_id"])
        options.append(
            CaptainOption(
                player_id=player_id, web_name=player["web_name"], position=ep.position,
                floor=ep.floor, median=ep.median, ceiling=ep.ceiling, confidence=ep.confidence,
                expected_minutes=ep.expected_minutes,
                is_penalty_taker=_is_penalty_taker(conn, player_id),
                opponent_short=opponent, is_home=is_home,
                selected_by_percent=player["selected_by_percent"],
            )
        )
    options.sort(key=lambda o: o.median, reverse=True)
    return options


@dataclass(frozen=True)
class CaptaincyReport:
    best: CaptainOption | None
    second: CaptainOption | None
    safe: CaptainOption | None
    high_upside: CaptainOption | None
    risks: list[str]


def captaincy_report(conn: sqlite3.Connection, squad_ids: list[int]) -> CaptaincyReport:
    options = evaluate_captaincy(conn, squad_ids)
    if not options:
        return CaptaincyReport(None, None, None, None, [])

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

    return CaptaincyReport(best=best, second=second, safe=safe, high_upside=high_upside, risks=risks)
