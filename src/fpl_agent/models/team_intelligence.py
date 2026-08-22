"""Persistent Team Intelligence - the qualitative half (Pillar 4, Team/Player
Intelligence pass, 2026-08-22). Real, disclosed scope: this project has no
free source for granular tactical shape (pressing, build-up patterns,
progression routes, width) - FotMob gives formation, possession, shots,
corners, and this project's own LLM-authored qualitative read
(tactical_signal/attacking_signal/defensive_signal), nothing finer-grained.
Rather than fabricate structured fields for data that doesn't exist, this
module surfaces exactly what's real: the current post-match qualitative
snapshot (team_qualitative_state, Slice A2) plus a real trend read over that
team's own match_observations history (qualitative_trends.py) - the memory
Slice A2's own current-state table never had. See `manager_intelligence.py`
for the separate, structurally-derived half (formation frequency, rotation,
substitution timing) built from real match_intelligence/team_match_state/
player_match_state rows rather than LLM-authored text.
"""
from dataclasses import dataclass

from fpl_agent.models.qualitative_trends import SignalTrend, signal_trends_for_subject


@dataclass(frozen=True)
class TeamQualitativeIntelligence:
    team_id: int
    team_name: str
    current_tactical_signal: str | None
    current_attacking_signal: str | None
    current_defensive_signal: str | None
    current_key_observation: str | None
    current_fpl_implication: str | None
    current_confidence: str | None
    last_match_id: int | None
    generated_at: str | None
    trends: list[SignalTrend]


def team_qualitative_intelligence(conn, team_id: int, lookback: int = 5) -> TeamQualitativeIntelligence:
    team_row = conn.execute("SELECT name FROM teams WHERE id=?", (team_id,)).fetchone()
    if team_row is None:
        raise ValueError(f"unknown team_id: {team_id}")

    state_row = conn.execute(
        "SELECT tactical_signal, attacking_signal, defensive_signal, key_observation, "
        "fpl_implication, confidence, match_id, generated_at "
        "FROM team_qualitative_state WHERE team_id=?", (team_id,),
    ).fetchone()

    trends = signal_trends_for_subject(conn, "team", team_id, lookback=lookback)

    return TeamQualitativeIntelligence(
        team_id=team_id, team_name=team_row["name"],
        current_tactical_signal=state_row["tactical_signal"] if state_row else None,
        current_attacking_signal=state_row["attacking_signal"] if state_row else None,
        current_defensive_signal=state_row["defensive_signal"] if state_row else None,
        current_key_observation=state_row["key_observation"] if state_row else None,
        current_fpl_implication=state_row["fpl_implication"] if state_row else None,
        current_confidence=state_row["confidence"] if state_row else None,
        last_match_id=state_row["match_id"] if state_row else None,
        generated_at=state_row["generated_at"] if state_row else None,
        trends=trends,
    )
