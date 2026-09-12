import sqlite3
from dataclasses import dataclass

# FPL official status codes: a=available, d=doubtful, i=injured, n=not eligible, s=suspended, u=unavailable
_CONFIRMED_OUT_STATUSES = {"s", "u", "n"}

_SEVERITY_ORDER = {
    "CONFIRMED UNAVAILABLE": 0,
    "LIKELY UNAVAILABLE": 1,
    "DOUBTFUL": 2,
    "FIT BUT MONITORED": 3,
    "FIT": 4,
}


def classify(status: str, chance_this: int | None, chance_next: int | None) -> str:
    """Section 45 classification, derived purely from official FPL fields.

    Real fix (2026-09-13, direct user complaint about a wildcard squad
    starting a real concussion doubt): every real caller of this function
    (expected_minutes/expected_points, squad building, transfers,
    captaincy, strategic planning) is making a decision about an UPCOMING
    gameweek, never about a round that has already locked - so
    `chance_of_playing_next_round` (FPL's own field for "how confident for
    the coming match") is the one that actually matters, not
    `chance_of_playing_this_round` (which reflects whatever round most
    recently locked, and can legitimately still read 100 - "fine for the
    match already underway" - while a real, fresh, separately-reported
    knock/return-to-play doubt for the NEXT match sits in `chance_next`
    instead). Confirmed live: a real player with a "Concussion - 50% chance
    of playing" news note had chance_this=100 (cleared for the already-live
    current gameweek) and chance_next=50 (the real doubt for the gameweek
    a wildcard squad is actually being built for) - the old `this`-first
    priority read him as fully fit and started him. `next` is now preferred
    whenever it exists; `this` remains the honest fallback for the (equally
    real) case where FPL hasn't published a next-round estimate yet."""
    if status in _CONFIRMED_OUT_STATUSES:
        return "CONFIRMED UNAVAILABLE"

    chance = chance_next if chance_next is not None else chance_this

    if status == "i":
        if chance is None or chance == 0:
            return "CONFIRMED UNAVAILABLE"
        return "LIKELY UNAVAILABLE" if chance <= 50 else "DOUBTFUL"

    if status == "d":
        return "LIKELY UNAVAILABLE" if chance is not None and chance <= 50 else "DOUBTFUL"

    # status == 'a'
    if (chance_this is not None and chance_this < 100) or (chance_next is not None and chance_next < 100):
        return "FIT BUT MONITORED"
    return "FIT"


@dataclass(frozen=True)
class PlayerAvailability:
    player_id: int
    web_name: str
    team: str
    status: str
    classification: str
    chance_of_playing_this_round: int | None
    chance_of_playing_next_round: int | None
    news: str | None
    news_added: str | None


_QUERY = """
SELECT
    p.id AS player_id, p.web_name, t.short_name AS team, p.status, p.news, p.news_added,
    s.chance_of_playing_this_round, s.chance_of_playing_next_round
FROM players p
JOIN teams t ON t.id = p.team_id
LEFT JOIN player_stats_snapshot s ON s.id = (
    SELECT id FROM player_stats_snapshot WHERE player_id = p.id ORDER BY retrieved_at DESC LIMIT 1
)
WHERE p.removed = 0
"""


def list_availability(conn: sqlite3.Connection, unavailable_only: bool = True) -> list[PlayerAvailability]:
    rows = conn.execute(_QUERY).fetchall()
    results = []
    for r in rows:
        cls = classify(r["status"], r["chance_of_playing_this_round"], r["chance_of_playing_next_round"])
        if unavailable_only and cls == "FIT":
            continue
        results.append(
            PlayerAvailability(
                player_id=r["player_id"],
                web_name=r["web_name"],
                team=r["team"],
                status=r["status"],
                classification=cls,
                chance_of_playing_this_round=r["chance_of_playing_this_round"],
                chance_of_playing_next_round=r["chance_of_playing_next_round"],
                news=r["news"],
                news_added=r["news_added"],
            )
        )
    results.sort(key=lambda p: _SEVERITY_ORDER[p.classification])
    return results
