"""Each club's next gameweeks as the team model sees them.

For every club and gameweek in the window: expected goals scored and conceded in
each fixture and the chance of a clean sheet, from the same odds-blended goals
every player projection reads (`expected_points._blended_fixture_goals`). Totals
over the window give an attack ranking and a defence ranking among the twenty
clubs. This is the team-as-a-whole layer the transfer decision can be explained
against: not a second model, the numbers the player projections already stand on,
gathered by club so a manager can see why a player's club is a good or bad one to
back right now. A blank gameweek is absent, a double has two entries, and
`market` marks fixtures where stored odds fed the goals (the rest are the model
alone)."""
import math
import sqlite3

DEFAULT_WINDOW_GW = 6


def team_fixture_outlook(conn: sqlite3.Connection, event: int, window: int = DEFAULT_WINDOW_GW) -> dict[int, dict]:
    from fpl_agent.models.expected_points import _blended_fixture_goals, _fixture_date

    teams = {r["id"]: dict(r) for r in conn.execute("SELECT id, code, name, short_name FROM teams")}
    by_team: dict[int, dict[int, list[dict]]] = {tid: {} for tid in teams}
    for f in conn.execute(
        "SELECT id, event, kickoff_time, team_h, team_a FROM fixtures WHERE finished=0 AND event >= ? AND event < ? "
        "ORDER BY event, kickoff_time", (event, event + window),
    ).fetchall():
        home_goals, away_goals = _blended_fixture_goals(conn, f["id"], f["team_h"], f["team_a"], _fixture_date(f))
        has_odds = conn.execute("SELECT 1 FROM fixture_odds_live WHERE fixture_id=? LIMIT 1", (f["id"],)).fetchone() is not None
        for tid, opp, gf, ga, at_home in (
            (f["team_h"], f["team_a"], home_goals, away_goals, True), (f["team_a"], f["team_h"], away_goals, home_goals, False),
        ):
            by_team[tid].setdefault(f["event"], []).append({
                "opponent": teams[opp]["short_name"], "opponent_code": teams[opp]["code"], "home": at_home,
                "xg_for": round(gf, 2), "xg_against": round(ga, 2), "cs": round(math.exp(-ga), 3), "market": has_odds,
            })

    out: dict[int, dict] = {}
    for tid, events in by_team.items():
        entries = [e for lst in events.values() for e in lst]
        if not entries:
            continue
        out[tid] = {
            "team_id": tid, "code": teams[tid]["code"], "name": teams[tid]["name"], "short": teams[tid]["short_name"],
            "events": {str(ev): lst for ev, lst in events.items()},
            "xg_for_total": round(sum(e["xg_for"] for e in entries), 2),
            "cs_total": round(sum(e["cs"] for e in entries), 2),
            "fixtures": len(entries),
        }
    for key, rank_key in (("xg_for_total", "attack_rank"), ("cs_total", "defence_rank")):
        ordered = sorted(out.values(), key=lambda r: -r[key])
        for rank, row in enumerate(ordered, start=1):
            row[rank_key] = rank
    for row in out.values():
        row["clubs_ranked"] = len(out)
    return out
