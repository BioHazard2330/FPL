"""The chance a player misses a fixture through yellow-card accumulation.

Premier League rule: five yellow cards in a club's first 19 league matches is a one-match ban, ten in the first 32 two
matches, fifteen in the first 38 three matches. FPL flags a player as suspended only once the ban is incurred, so until
then every projection treated a player on four yellows as if the next booking cost nothing. On 2026-10-27 five of the
user's fifteen were on three yellows with ten club matches left before the first cut-off.

Forward pass over the club's remaining fixtures in kickoff order: the distribution of the player's yellow count and of
ban matches still to serve. A ban is served in the club's next league match(es). In each match he is not banned he is
booked with probability 1 - exp(-yellow rate per 90 x expected fraction of 90 minutes). A domestic ban is served in the
club's next domestic matches, so a League Cup or FA Cup tie scheduled before the next league match takes one ban match
(BBC, 2026-10-26: Palmer's red-card ban falls on Chelsea's League Cup tie, not the next league game).

Assumptions, none fitted: the booking rate is the model's own shrunk card rate (`player_regression`, the same one the
cards component uses) and is constant across fixtures; only cup ties already stored count (a later round is unknown until
drawn); a red card is left to FPL's own flag."""
import math
import sqlite3

from fpl_agent.models.projection_memo import memoised_in_scope

THRESHOLDS = ((5, 19, 1), (10, 32, 2), (15, 38, 3))
_MAX_COUNT = 16


def _current_yellows(conn: sqlite3.Connection, player_id: int) -> int | None:
    row = conn.execute(
        "SELECT yellow_cards FROM player_stats_snapshot WHERE player_id=? ORDER BY retrieved_at DESC LIMIT 1", (player_id,),
    ).fetchone()
    return None if row is None or row["yellow_cards"] is None else int(row["yellow_cards"])


def _domestic_cups_before(conn: sqlite3.Connection, team_id: int, fixtures: list[tuple[int, int, bool]]) -> dict[int, int]:
    """{league fixture_id: domestic cup ties the club plays after the previous league fixture and before this one}."""
    try:
        cups = [r["kickoff_utc"] for r in conn.execute(
            "SELECT kickoff_utc FROM team_other_competition_fixtures WHERE team_id=? "
            "AND (competition LIKE 'EFL Cup%' OR competition LIKE 'FA Cup%') AND kickoff_utc IS NOT NULL", (team_id,),
        )]
    except sqlite3.OperationalError:
        return {}
    if not cups:
        return {}
    kickoff = {r["id"]: r["kickoff_time"] for r in conn.execute(
        "SELECT id, kickoff_time FROM fixtures WHERE team_h=? OR team_a=?", (team_id, team_id),
    )}
    out: dict[int, int] = {}
    previous = None
    for fixture_id, _, _ in fixtures:
        k = kickoff.get(fixture_id)
        if k is None:
            continue
        k = k.replace("Z", "+00:00")
        n = sum(1 for c in cups if (previous is None or c.replace("Z", "+00:00") > previous) and c.replace("Z", "+00:00") < k)
        if n:
            out[fixture_id] = n
        previous = k
    return out


def _club_fixtures(conn: sqlite3.Connection, team_id: int) -> list[tuple[int, int, bool]]:
    """(fixture_id, club match number, played) for every league fixture of the club, in kickoff order."""
    rows = conn.execute(
        "SELECT f.id, f.finished, f.kickoff_time, "
        "EXISTS (SELECT 1 FROM match_intelligence mi WHERE mi.fpl_fixture_id = f.id AND mi.status = 'FULL_TIME') AS ft "
        "FROM fixtures f WHERE (f.team_h=? OR f.team_a=?) ORDER BY COALESCE(f.kickoff_time, '9999'), f.id",
        (team_id, team_id),
    ).fetchall()
    return [(r["id"], i + 1, bool(r["finished"] or r["ft"])) for i, r in enumerate(rows)]


def ban_schedule(
    yellows: int, fixtures: list[tuple[int, int, bool]], p_booked: float, cups_before: dict[int, int] | None = None,
) -> dict[int, float]:
    """{fixture_id: probability he is serving a ban} over the unplayed fixtures. `cups_before` counts the domestic cup
    ties a club plays just before a league fixture; each serves one owed ban match."""
    state = {(min(yellows, _MAX_COUNT), 0): 1.0}
    out: dict[int, float] = {}
    first = True
    for fixture_id, number, played in fixtures:
        if played:
            continue
        cups = 0 if first else (cups_before or {}).get(fixture_id, 0)
        first = False
        if cups:
            served: dict[tuple[int, int], float] = {}
            for (count, owed), p in state.items():
                key = (count, max(owed - cups, 0))
                served[key] = served.get(key, 0.0) + p
            state = served
        banned = sum(p for (_, owed), p in state.items() if owed > 0)
        out[fixture_id] = banned
        nxt: dict[tuple[int, int], float] = {}
        for (count, owed), p in state.items():
            if owed > 0:
                nxt[(count, owed - 1)] = nxt.get((count, owed - 1), 0.0) + p
                continue
            nxt[(count, 0)] = nxt.get((count, 0), 0.0) + p * (1 - p_booked)
            new = min(count + 1, _MAX_COUNT)
            ban = next((length for limit, by_match, length in THRESHOLDS if new == limit and number <= by_match), 0)
            nxt[(new, ban)] = nxt.get((new, ban), 0.0) + p * p_booked
        state = nxt
    return out


@memoised_in_scope
def suspension_probabilities(conn: sqlite3.Connection, player_id: int, yellow90: float, minutes_fraction: float) -> dict[int, float]:
    """{fixture_id: chance of missing it through accumulated yellows}; empty when no threshold is still reachable."""
    yellows = _current_yellows(conn, player_id)
    team = conn.execute("SELECT team_id FROM players WHERE id=?", (player_id,)).fetchone()
    if yellows is None or team is None or yellow90 <= 0 or minutes_fraction <= 0:
        return {}
    fixtures = _club_fixtures(conn, team["team_id"])
    remaining = [f for f in fixtures if not f[2]]
    if not remaining:
        return {}
    first = remaining[0][1]
    if not any(yellows < limit and limit - yellows <= by_match - first + 1 for limit, by_match, _ in THRESHOLDS):
        return {}
    p_booked = 1 - math.exp(-yellow90 * minutes_fraction)
    cups = _domestic_cups_before(conn, team["team_id"], fixtures)
    return {k: v for k, v in ban_schedule(yellows, fixtures, p_booked, cups).items() if v > 0}


def suspension_probability(
    conn: sqlite3.Connection, player_id: int, fixture_id: int | None, yellow90: float | None, minutes_fraction: float,
) -> float:
    if fixture_id is None or not yellow90:
        return 0.0
    try:
        return suspension_probabilities(conn, player_id, round(yellow90, 4), round(minutes_fraction, 3)).get(fixture_id, 0.0)
    except sqlite3.OperationalError:
        return 0.0
