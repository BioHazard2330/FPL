"""Persistent Player Intelligence (Pillar 4, Team/Player Intelligence pass,
2026-08-22). Combines the existing current-state snapshot
(player_qualitative_state, Slice A2 - single latest row, overwritten every
FULL_TIME analysis) with a real trend read over that player's own
match_observations history (qualitative_trends.py) - the piece Slice A2
never had, since its own current-state table has no memory of what a
player's signal looked like BEFORE the latest match. Nothing here is
computed from anything but real, already-persisted rows; a player with no
qualitative analysis yet returns an honest empty/None state, never a
fabricated one.
"""
from dataclasses import dataclass

from fpl_agent.models.qualitative_trends import SignalTrend, signal_trends_for_subject


@dataclass(frozen=True)
class PlayerIntelligence:
    player_id: int
    web_name: str
    current_role: str | None
    current_tactical_signal: str | None
    current_fpl_outlook: str | None
    current_confidence: str | None
    last_match_id: int | None
    generated_at: str | None
    trends: list[SignalTrend]


def player_intelligence(conn, player_id: int, lookback: int = 5) -> PlayerIntelligence:
    player_row = conn.execute("SELECT web_name FROM players WHERE id=?", (player_id,)).fetchone()
    if player_row is None:
        raise ValueError(f"unknown player_id: {player_id}")

    state_row = conn.execute(
        "SELECT role, tactical_signal, fpl_outlook, confidence, match_id, generated_at "
        "FROM player_qualitative_state WHERE player_id=?", (player_id,),
    ).fetchone()

    trends = signal_trends_for_subject(conn, "player", player_id, lookback=lookback)

    return PlayerIntelligence(
        player_id=player_id, web_name=player_row["web_name"],
        current_role=state_row["role"] if state_row else None,
        current_tactical_signal=state_row["tactical_signal"] if state_row else None,
        current_fpl_outlook=state_row["fpl_outlook"] if state_row else None,
        current_confidence=state_row["confidence"] if state_row else None,
        last_match_id=state_row["match_id"] if state_row else None,
        generated_at=state_row["generated_at"] if state_row else None,
        trends=trends,
    )


def squad_player_intelligence(conn, player_ids: list[int], lookback: int = 5) -> list[PlayerIntelligence]:
    """One PlayerIntelligence per squad member who has at least one real
    FULL_TIME analysis on record (current state OR trend history) -
    players with zero qualitative evidence yet are silently omitted rather
    than returned as an all-None row, since there is nothing real to show
    for them."""
    out = []
    for pid in player_ids:
        pi = player_intelligence(conn, pid, lookback=lookback)
        if pi.current_role is not None or pi.trends:
            out.append(pi)
    return out
