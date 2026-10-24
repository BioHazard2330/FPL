"""What the matchday squad sheet says about each player, for his own fixture in a gameweek: in the starting eleven, on the
bench (and when he came on), or not in the squad at all (with FotMob's reason when it gives one). Read straight from the
stored FotMob lineup rows (`player_match_state`, `match_unavailable`, `match_coach`), and only once the lineup is the
official one (`match_intelligence.lineup_type` not "predicted") and the player's own team has rows - a guess is never
reported as a team sheet.

A player with no row in an official lineup is not on the bench: FotMob lists the starters and the substitutes, so a
player in neither list is outside the matchday squad. That is a different fact from a bench seat, and a different
projection (zero minutes against a small chance of a cameo)."""

import sqlite3
from dataclasses import dataclass

from fpl_agent.models.projection_memo import memoised_in_scope

STARTING = "STARTING"
BENCH = "BENCH"
NOT_IN_SQUAD = "NOT_IN_SQUAD"


@dataclass(frozen=True)
class MatchdayStatus:
    player_id: int
    match_id: int
    fixture_id: int
    match_status: str | None
    official: bool
    role: str | None
    minutes: int | None
    came_on: int | None
    went_off: int | None
    out_kind: str | None
    out_return: str | None
    coach: str | None
    formation: str | None

    @property
    def detail(self) -> str | None:
        if self.role == STARTING:
            bits = ["in the starting eleven"]
            if self.went_off:
                bits.append(f"off {self.went_off}'")
            elif self.minutes:
                bits.append(f"{self.minutes} min")
            return ", ".join(bits)
        if self.role == BENCH:
            if self.came_on:
                return f"on the bench, came on {self.came_on}'"
            if self.match_status == "FULL_TIME":
                return "on the bench, did not play"
            return "on the bench"
        if self.role == NOT_IN_SQUAD:
            if self.out_kind:
                bit = self.out_kind
                if self.out_return:
                    ret = self.out_return[:1].lower() + self.out_return[1:]
                    bit += f" ({ret})" if ret.split()[0] in ("doubtful", "unknown") else f" (back {ret})"
                return f"not in the matchday squad: {bit}"
            return "not in the matchday squad"
        return None


def _pick(rows: list[sqlite3.Row]) -> sqlite3.Row:
    open_rows = [r for r in rows if r["match_status"] != "FULL_TIME"]
    pool = open_rows or rows
    return sorted(pool, key=lambda r: r["kickoff_utc"] or "", reverse=not open_rows)[0]


def squad_matchday_status(
    conn: sqlite3.Connection, player_ids: list[int], event: int | None, fixture_id: int | None = None,
    match_id: int | None = None,
) -> dict[int, MatchdayStatus]:
    """Per player, his own match in `event` (the one still to be played if there are two); `fixture_id` pins one
    fixture, `match_id` pins one stored match and ignores `event`."""
    ids = list(dict.fromkeys(player_ids))
    if not ids or (event is None and match_id is None):
        return {}
    marks = ",".join("?" * len(ids))
    clauses = ""
    params: list = []
    if match_id is not None:
        clauses += " AND mi.id = ?"
        params.append(match_id)
    if fixture_id is not None:
        clauses += " AND f.id = ?"
        params.append(fixture_id)
    event_clause = "AND f.event = ?" if match_id is None else ""
    params = ([event] if match_id is None else []) + ids + params
    rows = conn.execute(
        f"""
        SELECT p.id AS player_id, p.team_id, f.id AS fixture_id, mi.id AS match_id, mi.status AS match_status,
               mi.lineup_type, mi.kickoff_utc,
               (SELECT COUNT(*) FROM player_match_state t WHERE t.match_id = mi.id AND t.team_id = p.team_id) AS team_rows,
               pms.started, pms.minutes, pms.substituted_on_minute, pms.substituted_off_minute,
               un.kind AS out_kind, un.expected_return AS out_return,
               mc.coach_name, mc.formation
        FROM players p
        JOIN fixtures f ON (f.team_h = p.team_id OR f.team_a = p.team_id) {event_clause}
        JOIN match_intelligence mi ON mi.fpl_fixture_id = f.id
        LEFT JOIN player_match_state pms ON pms.match_id = mi.id AND pms.player_id = p.id
        LEFT JOIN match_unavailable un ON un.match_id = mi.id AND un.player_id = p.id
        LEFT JOIN match_coach mc ON mc.match_id = mi.id AND mc.team_id = p.team_id
        WHERE p.id IN ({marks}){clauses}
        """,
        params,
    ).fetchall()
    by_player: dict[int, list[sqlite3.Row]] = {}
    for r in rows:
        by_player.setdefault(r["player_id"], []).append(r)
    out: dict[int, MatchdayStatus] = {}
    for pid, group in by_player.items():
        r = _pick(group)
        official = r["team_rows"] > 0 and r["lineup_type"] != "predicted"
        role = None
        if official:
            if r["started"] is None and r["minutes"] is None:
                role = NOT_IN_SQUAD
            else:
                role = STARTING if r["started"] else BENCH
        out[pid] = MatchdayStatus(
            player_id=pid, match_id=r["match_id"], fixture_id=r["fixture_id"], match_status=r["match_status"],
            official=official, role=role, minutes=r["minutes"],
            came_on=r["substituted_on_minute"], went_off=r["substituted_off_minute"],
            out_kind=r["out_kind"], out_return=r["out_return"], coach=r["coach_name"], formation=r["formation"],
        )
    return out


@memoised_in_scope
def latest_sheet_roles(conn: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    """Each player's role in the most recent finished match whose official sheet is stored: {player_id: (role, kickoff)}."""
    rows = conn.execute(
        """
        SELECT p.id AS pid, mi.kickoff_utc AS k, s.started AS st, s.minutes AS mn
        FROM players p
        JOIN match_intelligence mi ON (mi.home_team_id = p.team_id OR mi.away_team_id = p.team_id)
        LEFT JOIN player_match_state s ON s.match_id = mi.id AND s.player_id = p.id
        WHERE mi.status = 'FULL_TIME' AND mi.lineup_type != 'predicted' AND p.removed = 0
          AND EXISTS (SELECT 1 FROM player_match_state t WHERE t.match_id = mi.id AND t.team_id = p.team_id)
        ORDER BY mi.kickoff_utc
        """
    ).fetchall()
    out: dict[int, tuple[str, str]] = {}
    for r in rows:
        role = NOT_IN_SQUAD if r["st"] is None and r["mn"] is None else (STARTING if r["st"] else BENCH)
        out[r["pid"]] = (role, r["k"])
    return out
