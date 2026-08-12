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
    """Section 45 classification, derived purely from official FPL fields."""
    if status in _CONFIRMED_OUT_STATUSES:
        return "CONFIRMED UNAVAILABLE"

    chance = chance_this if chance_this is not None else chance_next

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
