"""Real, unified per-player lineup state (2026-08-22, automation-lifecycle pass) -
the single place that answers "is this player predicted to start, confirmed
starting, confirmed benched, or unavailable" for a given gameweek, replacing the
dashboard's previous predicted-lineup-only badge with a real PREDICTED vs
CONFIRMED distinction.

Real, live-confirmed fact this session: FotMob publishes a genuine confirmed
starting lineup BEFORE kickoff - `player_match_state` gets populated (~11 rows per
team) while `match_intelligence.status` is still `PRE_MATCH` (verified live against
real GW1 fixtures still hours from kickoff). So "player_match_state has any rows
for this player's own match" is a real, reliable "lineup confirmed" signal, not
just a post-match boxscore artifact.

Priority, most decisive first: official unavailability (Tier 1, `players.status`)
beats a confirmed lineup beats a mere prediction beats no signal at all - a player
flagged unavailable by FPL itself is reported as such even if some stale predicted-
lineup row still says "starting"."""

import sqlite3
from dataclasses import dataclass

from fpl_agent.ingestion.lineup_probability_source import get_start_percent
from fpl_agent.ingestion.predicted_lineups_source import get_predicted_lineup_for_squad
from fpl_agent.models.availability import classify

_STATE_PREDICTED_START = "PREDICTED_START"
_STATE_CONFIRMED_STARTING = "CONFIRMED_STARTING"
_STATE_CONFIRMED_BENCHED = "CONFIRMED_BENCHED"
_STATE_OUT_UNAVAILABLE = "OUT_UNAVAILABLE"
_STATE_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class LineupState:
    player_id: int
    state: str
    detail: str | None
    source: str  # "availability" | "confirmed_lineup" | "predicted_lineup" | "none"


def _availability_states(conn: sqlite3.Connection, player_ids: list[int]) -> dict[int, LineupState]:
    if not player_ids:
        return {}
    placeholders = ",".join("?" * len(player_ids))
    rows = conn.execute(
        f"SELECT p.id AS player_id, p.status, s.chance_of_playing_this_round, s.chance_of_playing_next_round "
        f"FROM players p LEFT JOIN player_stats_snapshot s ON s.id = ("
        f"  SELECT id FROM player_stats_snapshot WHERE player_id = p.id ORDER BY retrieved_at DESC LIMIT 1"
        f") WHERE p.id IN ({placeholders})",
        player_ids,
    ).fetchall()
    out: dict[int, LineupState] = {}
    for r in rows:
        cls = classify(r["status"], r["chance_of_playing_this_round"], r["chance_of_playing_next_round"])
        if cls == "CONFIRMED UNAVAILABLE":
            out[r["player_id"]] = LineupState(r["player_id"], _STATE_OUT_UNAVAILABLE, cls, "availability")
    return out


def _confirmed_lineup_states(conn: sqlite3.Connection, player_ids: list[int], event: int) -> dict[int, LineupState]:
    if not player_ids:
        return {}
    placeholders = ",".join("?" * len(player_ids))
    # Each player's own real fixture for this event, then whether that match's
    # lineup has been confirmed (player_match_state populated) and whether this
    # player is among the confirmed rows.
    rows = conn.execute(
        f"""
        SELECT p.id AS player_id, mi.id AS match_id,
               (SELECT COUNT(*) FROM player_match_state pms WHERE pms.match_id = mi.id) AS lineup_rows,
               EXISTS(
                   SELECT 1 FROM player_match_state pms
                   WHERE pms.match_id = mi.id AND pms.player_id = p.id
               ) AS is_starting
        FROM players p
        JOIN fixtures f ON (f.team_h = p.team_id OR f.team_a = p.team_id) AND f.event = ?
        JOIN match_intelligence mi ON mi.fpl_fixture_id = f.id
        WHERE p.id IN ({placeholders})
        """,
        (event, *player_ids),
    ).fetchall()
    out: dict[int, LineupState] = {}
    for r in rows:
        if r["lineup_rows"] == 0:
            continue  # not confirmed yet - leave for the predicted-lineup fallback
        if r["is_starting"]:
            out[r["player_id"]] = LineupState(
                r["player_id"], _STATE_CONFIRMED_STARTING, "in the confirmed starting lineup", "confirmed_lineup"
            )
        else:
            out[r["player_id"]] = LineupState(
                r["player_id"], _STATE_CONFIRMED_BENCHED,
                "not in the confirmed starting lineup for this match", "confirmed_lineup",
            )
    return out


def _predicted_states(conn: sqlite3.Connection, player_ids: list[int]) -> dict[int, LineupState]:
    if not player_ids:
        return {}
    predicted = get_predicted_lineup_for_squad(conn, player_ids)
    out: dict[int, LineupState] = {}
    for pid in player_ids:
        info = predicted.get(pid)
        percent = get_start_percent(conn, pid)
        if info is None and percent is None:
            continue
        bits = []
        if info is not None:
            bits.append(info["status"])
        if percent is not None:
            bits.append(f"{percent}% predicted start")
        out[pid] = LineupState(pid, _STATE_PREDICTED_START, " · ".join(bits) or None, "predicted_lineup")
    return out


def squad_lineup_states(conn: sqlite3.Connection, player_ids: list[int], event: int | None) -> dict[int, "LineupState"]:
    """Batched resolver - one real query per tier instead of N+1 per-player
    lookups. Priority: OUT_UNAVAILABLE > confirmed lineup > predicted lineup >
    UNKNOWN (no signal from any source)."""
    ids = list(dict.fromkeys(player_ids))  # de-dupe, preserve order
    if not ids:
        return {}

    out_states = _availability_states(conn, ids)
    remaining = [pid for pid in ids if pid not in out_states]

    confirmed_states = _confirmed_lineup_states(conn, remaining, event) if (remaining and event is not None) else {}
    remaining = [pid for pid in remaining if pid not in confirmed_states]

    predicted_states = _predicted_states(conn, remaining) if remaining else {}

    result: dict[int, LineupState] = {}
    for pid in ids:
        if pid in out_states:
            result[pid] = out_states[pid]
        elif pid in confirmed_states:
            result[pid] = confirmed_states[pid]
        elif pid in predicted_states:
            result[pid] = predicted_states[pid]
        else:
            result[pid] = LineupState(pid, _STATE_UNKNOWN, None, "none")
    return result


def resolve_lineup_state(conn: sqlite3.Connection, player_id: int, event: int | None) -> LineupState:
    return squad_lineup_states(conn, [player_id], event)[player_id]
