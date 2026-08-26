"""Real penalty-duty signal, data-capture half only (2026-08-26,
GW1-postmortem gap audit, P1 "penalty-duty extraction"). See the audit's own
explicit instruction: "Do NOT invent penalty-taker probabilities if the
database cannot support them. Instead explicitly identify where the data is
missing and whether a defensible proxy can be constructed."

FotMob's real shotmap payload carries a genuine `situation` field per shot -
verified LIVE before writing a single line of this, not assumed: fetched all
10 real GW1 matches and found exactly 2 real shots with
`situation == "Penalty"` (Brentford v Spurs, Newcastle v Liverpool). The
field is real and reliable; `models/match_intelligence.py::
_shot_aggregates_by_player` now parses it into `player_match_state.
penalty_shots`/`penalty_goals` (migration 0031) - real, already-fetched
data, zero new ingestion cost.

What this module deliberately does NOT do: feed anything into
`expected_points.py`. Real, current penalty duty (WHO takes penalties) is
already known with certainty from official Tier-1 `players.penalties_order`
data and already reaches captaincy's `is_penalty_taker` flag - that gap was
already closed. The genuinely open question is HOW MUCH a real penalty rate
should add on top of a player's shrinkage-regressed historical goals rate,
and answering that honestly needs real match volume this project doesn't
have yet: 2 real penalty shots league-wide after 1 real gameweek is not a
sample size any real conversion/uplift rate could be defensibly fit from -
doing so would be exactly the premature calibration this project's own
standing rule (and this audit's own explicit "do not fabricate" instruction)
forbids. `league_penalty_evidence()` reports the real, current state of that
evidence honestly (including `sufficient_for_adjustment=False` for as long as
it remains true) rather than silently building a number nobody asked to be
computed from too little data. Revisit wiring an actual xP adjustment once
`sufficient_for_adjustment` is genuinely True - the capture pipeline will
already have real data waiting for it, no further ingestion work needed.
"""
import sqlite3
from dataclasses import dataclass

# Real, disclosed, uncalibrated minimum - the real point is not this exact
# number but that a number is required at all before this project would
# trust a league-wide penalty conversion rate enough to act on it. 20 real
# penalty shots is itself a bar many EPL seasons don't fully clear early on,
# stated honestly rather than picked to look easily reachable.
_MIN_LEAGUE_WIDE_PENALTY_SHOTS = 20


@dataclass(frozen=True)
class PenaltyDutyEvidence:
    league_penalty_shots: int
    league_penalty_goals: int
    league_conversion_rate: float | None
    sufficient_for_adjustment: bool


def league_penalty_evidence(conn: sqlite3.Connection) -> PenaltyDutyEvidence:
    """Real, current, league-wide aggregate over every real penalty shot
    this project has actually observed via FotMob so far - grows
    automatically as more real gameweeks are analyzed, no code change
    needed when it eventually clears the threshold."""
    row = conn.execute(
        "SELECT COALESCE(SUM(penalty_shots), 0) AS shots, COALESCE(SUM(penalty_goals), 0) AS goals "
        "FROM player_match_state WHERE penalty_shots IS NOT NULL"
    ).fetchone()
    shots = row["shots"] or 0
    goals = row["goals"] or 0
    conversion = round(goals / shots, 4) if shots > 0 else None
    return PenaltyDutyEvidence(
        league_penalty_shots=shots, league_penalty_goals=goals,
        league_conversion_rate=conversion,
        sufficient_for_adjustment=shots >= _MIN_LEAGUE_WIDE_PENALTY_SHOTS,
    )
