"""Manager Intelligence - the structurally-derived half (Pillar 4,
Team/Player Intelligence pass, 2026-08-22). Real, disclosed scope: this
project tracks no separate "manager" entity (no source gives manager
identity/tenure independent of the team) - what's built here is a real,
evidence-based TEAM-level tactical-pattern profile (formation frequency,
substitution timing, starting-XI rotation) aggregated across that team's own
match history, which is the closest honest proxy to "manager tendencies" a
free-resources-only project without a manager-identity source can build
without fabricating one. A real manager change (models/manager_change.py,
Pillar 2) invalidates the historical continuity of this profile - the
caller's job to check that signal separately, not this module's, since this
module has no way to know when a manager actually changed.
"""
from collections import Counter
from dataclasses import dataclass

_MIN_MATCHES_FOR_PATTERN = 2


@dataclass(frozen=True)
class ManagerIntelligence:
    team_id: int
    team_name: str
    matches_observed: int
    formation_frequency: dict[str, int]  # formation string -> real count of FULL_TIME matches using it
    most_common_formation: str | None
    avg_first_substitution_minute: float | None
    starting_xi_rotation_rate: float | None  # 0.0 = never changes the XI, 1.0 = a completely different XI every match
    note: str | None  # honest "insufficient history" explanation when matches_observed is too low to say more


def _jaccard_distance(a: set[int], b: set[int]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return 1.0 - (len(a & b) / len(union))


def manager_intelligence(conn, team_id: int) -> ManagerIntelligence:
    team_row = conn.execute("SELECT name FROM teams WHERE id=?", (team_id,)).fetchone()
    if team_row is None:
        raise ValueError(f"unknown team_id: {team_id}")

    match_rows = conn.execute(
        "SELECT mi.id AS match_id, tms.formation "
        "FROM match_intelligence mi JOIN team_match_state tms ON tms.match_id = mi.id "
        "WHERE tms.team_id=? AND mi.status='FULL_TIME' ORDER BY mi.kickoff_utc ASC",
        (team_id,),
    ).fetchall()

    if len(match_rows) < _MIN_MATCHES_FOR_PATTERN:
        return ManagerIntelligence(
            team_id=team_id, team_name=team_row["name"], matches_observed=len(match_rows),
            formation_frequency={}, most_common_formation=None, avg_first_substitution_minute=None,
            starting_xi_rotation_rate=None,
            note=f"only {len(match_rows)} real FULL_TIME match(es) observed for this team - "
                 f"need at least {_MIN_MATCHES_FOR_PATTERN} to say anything about tendencies honestly",
        )

    formation_counts = Counter(r["formation"] for r in match_rows if r["formation"])
    most_common = formation_counts.most_common(1)[0][0] if formation_counts else None

    first_sub_minutes = []
    starting_xis: list[set[int]] = []
    for row in match_rows:
        subs = conn.execute(
            "SELECT MIN(substituted_off_minute) AS m FROM player_match_state "
            "WHERE match_id=? AND team_id=? AND substituted_off_minute IS NOT NULL",
            (row["match_id"], team_id),
        ).fetchone()
        if subs and subs["m"] is not None:
            first_sub_minutes.append(subs["m"])

        xi = {
            r["player_id"] for r in conn.execute(
                "SELECT player_id FROM player_match_state WHERE match_id=? AND team_id=? AND started=1",
                (row["match_id"], team_id),
            ).fetchall() if r["player_id"] is not None
        }
        starting_xis.append(xi)

    avg_first_sub = round(sum(first_sub_minutes) / len(first_sub_minutes), 1) if first_sub_minutes else None

    rotation_distances = [
        _jaccard_distance(starting_xis[i], starting_xis[i + 1])
        for i in range(len(starting_xis) - 1)
        if starting_xis[i] and starting_xis[i + 1]  # both sides need a real resolved XI to compare honestly
    ]
    rotation_rate = round(sum(rotation_distances) / len(rotation_distances), 2) if rotation_distances else None

    return ManagerIntelligence(
        team_id=team_id, team_name=team_row["name"], matches_observed=len(match_rows),
        formation_frequency=dict(formation_counts), most_common_formation=most_common,
        avg_first_substitution_minute=avg_first_sub, starting_xi_rotation_rate=rotation_rate,
        note=None,
    )
