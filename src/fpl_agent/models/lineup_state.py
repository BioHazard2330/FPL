"""Real, unified per-player lineup state (2026-08-22, automation-lifecycle pass) -
the single place that answers "is this player predicted to start, confirmed
starting, confirmed benched, or unavailable" for a given gameweek, replacing the
dashboard's previous predicted-lineup-only badge with a real PREDICTED vs
CONFIRMED distinction.

Real, live-confirmed fact (revised 2026-09-12 - the earlier version of this
claim was wrong and shipped a real bug): `player_match_state` gets populated
BEFORE kickoff, sometimes hours before, but that alone is NOT a "lineup
confirmed" signal - FotMob's own `content.lineup.lineupType` field
(`match_intelligence.lineup_type`) distinguishes a real "predicted" lineup
(source "enetpulse", a third-party guess, populated as soon as FotMob has
one - confirmed live against every real GW4 PRE_MATCH fixture, still ~90
minutes from kickoff) from "standard" (the lineup that was actually used,
confirmed live against six real already-played matches). The bug this
fixes: every squad player was showing CONFIRMED_STARTING/CONFIRMED_BENCHED
well before any real official teamsheet exists, because the code only
ever checked "does player_match_state have rows for this match", never
which kind of lineup those rows came from. Real official teamsheets don't
drop until close to kickoff (well-known football convention, not
independently re-derived here) - a "predicted" lineup_type now falls
through to the real predicted-lineup fallback below instead.

A bench seat and absence from the matchday squad are different states: FotMob lists starters and substitutes, so a
player in neither list is CONFIRMED_NOT_IN_SQUAD (see `models/matchday_status.py`). Before 2026-10-25 any stored row
counted as "starting", so a substitute showed as confirmed and an omitted player as benched.

Priority, most decisive first: official unavailability (Tier 1, `players.status`)
beats a confirmed lineup beats a mere prediction beats no signal at all - a player
flagged unavailable by FPL itself is reported as such even if some stale predicted-
lineup row still says "starting"."""

import sqlite3
from dataclasses import dataclass

from fpl_agent.ingestion.lineup_probability_source import get_start_percent
from fpl_agent.ingestion.predicted_lineups_source import get_predicted_lineup_for_squad
from fpl_agent.models.availability import classify
from fpl_agent.models.matchday_status import BENCH, NOT_IN_SQUAD, STARTING, squad_matchday_status

_STATE_PREDICTED_START = "PREDICTED_START"
_STATE_CONFIRMED_STARTING = "CONFIRMED_STARTING"
_STATE_CONFIRMED_BENCHED = "CONFIRMED_BENCHED"
_STATE_CONFIRMED_NOT_IN_SQUAD = "CONFIRMED_NOT_IN_SQUAD"
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


def _confirmed_lineup_states(
    conn: sqlite3.Connection, player_ids: list[int], event: int, fixture_id: int | None = None,
) -> dict[int, LineupState]:
    out: dict[int, LineupState] = {}
    for pid, st in squad_matchday_status(conn, player_ids, event, fixture_id).items():
        if st.role == STARTING:
            out[pid] = LineupState(pid, _STATE_CONFIRMED_STARTING, st.detail, "confirmed_lineup")
        elif st.role == BENCH:
            out[pid] = LineupState(pid, _STATE_CONFIRMED_BENCHED, st.detail, "confirmed_lineup")
        elif st.role == NOT_IN_SQUAD:
            out[pid] = LineupState(pid, _STATE_CONFIRMED_NOT_IN_SQUAD, st.detail, "confirmed_lineup")
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


def squad_lineup_states(
    conn: sqlite3.Connection, player_ids: list[int], event: int | None, fixture_id: int | None = None,
) -> dict[int, "LineupState"]:
    """Batched resolver - one real query per tier instead of N+1 per-player
    lookups. Priority: OUT_UNAVAILABLE > confirmed lineup > predicted lineup >
    UNKNOWN (no signal from any source)."""
    ids = list(dict.fromkeys(player_ids))  # de-dupe, preserve order
    if not ids:
        return {}

    out_states = _availability_states(conn, ids)
    remaining = [pid for pid in ids if pid not in out_states]

    confirmed_states = _confirmed_lineup_states(conn, remaining, event, fixture_id) if (remaining and event is not None) else {}
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


def resolve_lineup_state(
    conn: sqlite3.Connection, player_id: int, event: int | None, fixture_id: int | None = None,
) -> LineupState:
    return squad_lineup_states(conn, [player_id], event, fixture_id)[player_id]
