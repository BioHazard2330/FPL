import sqlite3
from dataclasses import dataclass

from fpl_agent.models.availability import classify

_AVAILABILITY_DAMPING = {
    "FIT": 1.0,
    "FIT BUT MONITORED": 0.85,
    "DOUBTFUL": 0.5,
    "LIKELY UNAVAILABLE": 0.15,
    "CONFIRMED UNAVAILABLE": 0.0,
}

# Approximate round count used to convert a cross-league total-minutes figure
# into a per-GW rate (models/cross_league_source.py's CROSS_LEAGUE_CODES: La
# Liga/Serie A play 38 rounds, Bundesliga/Ligue 1 play 34, RFPL ~30 - 38 is a
# disclosed, deliberately simple approximation, not a per-league lookup table
# (getting a specific league's exact round count wrong would silently bias
# one nationality's signings without being any more honest about it - a
# single documented constant plus the discount below is the more defensible
# trade-off for a LOW-confidence estimate that already carries real
# uncertainty from the transfer itself).
_CROSS_LEAGUE_ROUNDS_APPROX = 38
# A real transfer doesn't guarantee immediate first-team minutes at the new
# club (squad depth, manager trust, an adaptation period) - this is a
# disclosed, uncalibrated heuristic, same honesty posture as
# squad_churn.py's _CHURN_SHRINK_CAP and promoted_team_calibration.py's
# additive shift. Revisit once real in-season minutes data exists for any
# of these signings to fit an actual rate against.
_NEW_SIGNING_MINUTES_DISCOUNT = 0.6


@dataclass(frozen=True)
class ExpectedMinutes:
    player_id: int
    expected_minutes: float
    confidence: str  # LOW / MEDIUM / HIGH
    basis: str
    classification: str


def expected_minutes(conn: sqlite3.Connection, player_id: int) -> ExpectedMinutes:
    player = conn.execute("SELECT status FROM players WHERE id=?", (player_id,)).fetchone()
    if player is None:
        raise ValueError(f"unknown player_id: {player_id}")

    snapshot = conn.execute(
        "SELECT minutes, chance_of_playing_this_round, chance_of_playing_next_round "
        "FROM player_stats_snapshot WHERE player_id=? ORDER BY retrieved_at DESC LIMIT 1",
        (player_id,),
    ).fetchone()
    chance_this = snapshot["chance_of_playing_this_round"] if snapshot else None
    chance_next = snapshot["chance_of_playing_next_round"] if snapshot else None
    classification = classify(player["status"], chance_this, chance_next)

    finished_events = conn.execute("SELECT COUNT(*) AS n FROM events WHERE finished=1").fetchone()["n"]
    current_minutes = snapshot["minutes"] if snapshot else None

    current_per_gw = None
    if finished_events > 0 and current_minutes is not None:
        current_per_gw = min(current_minutes / finished_events, 90)

    prior_row = conn.execute(
        "SELECT minutes FROM player_season_history WHERE player_id=? ORDER BY season_name DESC LIMIT 1",
        (player_id,),
    ).fetchone()
    prior_per_gw = min(prior_row["minutes"] / 38, 90) if prior_row and prior_row["minutes"] is not None else None

    if current_per_gw is not None and prior_per_gw is not None:
        weight_current = min(finished_events / 10, 0.8)
        base = weight_current * current_per_gw + (1 - weight_current) * prior_per_gw
        confidence = "MEDIUM" if finished_events < 10 else "HIGH"
        basis = "blended_current_and_prior_season"
    elif current_per_gw is not None:
        base = current_per_gw
        confidence = "MEDIUM" if finished_events < 5 else "HIGH"
        basis = "current_season_only"
    elif prior_per_gw is not None:
        base = prior_per_gw
        confidence = "LOW"
        basis = "last_season_prior_no_current_data"
    else:
        cross_league_row = conn.execute(
            "SELECT minutes FROM player_cross_league_prior WHERE player_id=?", (player_id,)
        ).fetchone()
        if cross_league_row is not None and cross_league_row["minutes"]:
            cross_league_per_gw = min(cross_league_row["minutes"] / _CROSS_LEAGUE_ROUNDS_APPROX, 90)
            base = cross_league_per_gw * _NEW_SIGNING_MINUTES_DISCOUNT
            confidence = "LOW"
            basis = "cross_league_prior_new_signing"
        else:
            base = 0.0
            confidence = "LOW"
            basis = "no_data_available"

    damped = min(base * _AVAILABILITY_DAMPING[classification], 90.0)

    return ExpectedMinutes(
        player_id=player_id,
        expected_minutes=round(damped, 1),
        confidence=confidence,
        basis=basis,
        classification=classification,
    )
