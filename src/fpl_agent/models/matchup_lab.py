"""MATCHUP LAB: where a team's chances come from, laid against where its
opponent gives them up.

Every shot in `match_shots` has a situation (open play, corner, set piece,
throw-in, fast break, penalty). A team's attack has a profile over those
sources and so does an opponent's defence. For a fixture, the expected xG from
a source is the league's average for that source scaled by how much the
attacking team over- or under-produces it and how much the defending team over-
or under-concedes it. A corner-heavy attack against a side that gives away
corners lands in the output as extra corner xG for that fixture, with the
players who actually take those shots.

It is a lens, not an input. The projections' goals come from the odds-blended
Dixon-Coles model; this view does not feed them, because a season of 65
matches is too few to move a team's goal expectation and the lens would only
re-count what the model already has. Where it matters is in the shape of the
goals and in who gets them.

Numerical assumptions:
- Ratios are shrunk toward 1 with `SHRINK_MATCHES` (8) matches of league-
  average evidence, so a side with 5 matches moves about 38% of the way to its
  observed ratio. The constant is a judgement; at 65 matches league-wide
  nothing sharper is defensible.
- The two ratios multiply (independent attack and defence effects, no
  interaction), and the product is clipped to [0.4, 2.5] per source.
- xG here is the shot xG FotMob publishes; expected goals in the lens are on
  that scale, which runs about 4% below FPL's goals on average, and are shown
  as shifts against the league's average fixture, not as a second forecast.
"""
import sqlite3
from collections import defaultdict

SOURCES: dict[str, tuple[str, ...]] = {
    "open play": ("RegularPlay", "IndividualPlay"),
    "corners": ("FromCorner",),
    "set pieces": ("SetPiece", "FreeKick", "ThrowInSetPiece"),
    "fast breaks": ("FastBreak",),
    "penalties": ("Penalty",),
}
_SOURCE_OF = {situation: source for source, situations in SOURCES.items() for situation in situations}

SHRINK_MATCHES = 8.0
RATIO_FLOOR, RATIO_CEILING = 0.4, 2.5


def team_profiles(conn: sqlite3.Connection) -> dict[int, dict]:
    """Per FPL team: matches with stored shots, and xG for and against by
    source, summed over its finished matches."""
    rows = conn.execute(
        "SELECT mi.id AS match_id, mi.home_team_id AS home, mi.away_team_id AS away, "
        "       s.team_id AS shooter, s.situation AS situation, s.xg AS xg "
        "FROM match_intelligence mi JOIN match_shots s ON s.match_id = mi.id "
        "WHERE mi.status = 'FULL_TIME' AND s.xg IS NOT NULL"
    ).fetchall()
    profiles: dict[int, dict] = defaultdict(lambda: {"matches": set(), "for": defaultdict(float), "against": defaultdict(float)})
    for r in rows:
        source = _SOURCE_OF.get(r["situation"])
        if source is None:
            continue
        opponent = r["away"] if r["shooter"] == r["home"] else r["home"]
        profiles[r["shooter"]]["matches"].add(r["match_id"])
        profiles[r["shooter"]]["for"][source] += r["xg"]
        profiles[opponent]["matches"].add(r["match_id"])
        profiles[opponent]["against"][source] += r["xg"]
    return {
        t: {"matches": len(p["matches"]), "for": dict(p["for"]), "against": dict(p["against"])}
        for t, p in profiles.items()
    }


def league_means(profiles: dict[int, dict]) -> dict[str, float]:
    """Average xG per team-match by source."""
    team_matches = sum(p["matches"] for p in profiles.values())
    if team_matches == 0:
        return {s: 0.0 for s in SOURCES}
    return {s: sum(p["for"].get(s, 0.0) for p in profiles.values()) / team_matches for s in SOURCES}


def shrunk_ratio(total: float, matches: int, league_mean: float) -> float:
    """A team's per-match xG from one source against the league's, pulled
    toward 1 by `SHRINK_MATCHES` matches of average evidence."""
    if league_mean <= 0:
        return 1.0
    return (total + SHRINK_MATCHES * league_mean) / ((matches + SHRINK_MATCHES) * league_mean)


def side_lens(profiles: dict[int, dict], means: dict[str, float], attacker: int, defender: int) -> list[dict]:
    att = profiles.get(attacker)
    dfn = profiles.get(defender)
    out = []
    for source in SOURCES:
        mean = means.get(source, 0.0)
        a = shrunk_ratio(att["for"].get(source, 0.0), att["matches"], mean) if att else 1.0
        d = shrunk_ratio(dfn["against"].get(source, 0.0), dfn["matches"], mean) if dfn else 1.0
        factor = min(max(a * d, RATIO_FLOOR), RATIO_CEILING)
        out.append({
            "source": source, "league": round(mean, 3), "attack": round(a, 2), "defence": round(d, 2),
            "expected": round(mean * factor, 3), "shift": round(mean * factor - mean, 3),
        })
    return out


def fixture_lens(profiles: dict[int, dict], means: dict[str, float], home: int, away: int) -> dict:
    home_rows = side_lens(profiles, means, home, away)
    away_rows = side_lens(profiles, means, away, home)
    return {
        "home": home_rows, "away": away_rows,
        "matches": {"home": profiles.get(home, {}).get("matches", 0), "away": profiles.get(away, {}).get("matches", 0)},
        "headline": _headline(home_rows, away_rows),
    }


def _headline(home_rows: list[dict], away_rows: list[dict]) -> dict | None:
    """The single largest shift against the league's average fixture, with
    the side it favours, if any shift is worth saying out loud (0.08 xG)."""
    best = None
    for side, rows in (("home", home_rows), ("away", away_rows)):
        for r in rows:
            if best is None or abs(r["shift"]) > abs(best["shift"]):
                best = {"side": side, **r}
    if best is None or abs(best["shift"]) < 0.08:
        return None
    return best


def source_takers(conn: sqlite3.Connection, team_id: int, source: str, limit: int = 3) -> list[dict]:
    """The players with the most xG from `source` situations for a team this
    season, from stored shots."""
    situations = SOURCES[source]
    marks = ",".join("?" for _ in situations)
    rows = conn.execute(
        f"SELECT s.player_id AS pid, p.web_name AS name, SUM(s.xg) AS xg, COUNT(*) AS shots "
        f"FROM match_shots s JOIN match_intelligence mi ON mi.id = s.match_id JOIN players p ON p.id = s.player_id "
        f"WHERE mi.status = 'FULL_TIME' AND s.team_id = ? AND s.situation IN ({marks}) AND s.player_id IS NOT NULL "
        f"GROUP BY s.player_id ORDER BY xg DESC LIMIT ?",
        (team_id, *situations, limit),
    ).fetchall()
    return [{"player_id": r["pid"], "name": r["name"], "xg": round(r["xg"], 2), "shots": r["shots"]} for r in rows]
