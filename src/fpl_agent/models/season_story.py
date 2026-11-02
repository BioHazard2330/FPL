"""THE SEASON STORY - the manager's season so far as data for a scroll-driven page: every finished gameweek's points,
rank, the average, the chip and the armband; the race against the managers ranked around 10,000 (their mean running
total) and against the race league; and the moments (best and worst week against the average, biggest rank rise and
fall, best armband, worst bench) picked out of those rows. Reads stored rows only."""
import sqlite3
from collections import defaultdict
from statistics import mean


def season_story(conn: sqlite3.Connection, entry_id: int) -> dict | None:
    from fpl_agent.ingestion.cohort import COHORT
    from fpl_agent.ingestion.leagues import race_league
    from fpl_agent.models.rules import current_season

    season = current_season(conn)
    rows = [dict(r) for r in conn.execute("SELECT * FROM my_team_gw_summary WHERE entry_id = ? ORDER BY event", (entry_id,))]
    finished = {r["id"] for r in conn.execute("SELECT id FROM events WHERE finished = 1")}
    rows = [r for r in rows if r["event"] in finished]
    if not rows:
        return None
    avg = {r["id"]: r["average_entry_score"] for r in conn.execute("SELECT id, average_entry_score FROM events")}
    names = {r["id"]: (r["web_name"], r["code"], r["team_code"]) for r in conn.execute(
        "SELECT p.id, p.web_name, p.code, t.code AS team_code FROM players p JOIN teams t ON t.id = p.team_id")}
    picks = defaultdict(list)
    chips = {}
    for p in conn.execute("SELECT event, player_id, multiplier, is_captain, active_chip FROM my_team_picks WHERE entry_id = ?", (entry_id,)):
        picks[p["event"]].append(dict(p))
        if p["active_chip"]:
            chips[p["event"]] = p["active_chip"]

    weeks = []
    for r in rows:
        ev = r["event"]
        pts = {x["player_id"]: x["total_points"] for x in conn.execute(
            "SELECT player_id, SUM(total_points) AS total_points FROM player_gw_stats WHERE season = ? AND event = ? GROUP BY player_id", (season, ev))}
        cap = next((p for p in picks[ev] if p["is_captain"]), None)
        xi = [p for p in picks[ev] if p["multiplier"] > 0]
        star = max(xi, key=lambda p: pts.get(p["player_id"], 0), default=None)
        weeks.append({
            "event": ev, "points": r["points"] - (r["event_transfers_cost"] or 0), "total": r["total_points"], "rank": r["overall_rank"],
            "average": avg.get(ev), "bench": r["points_on_bench"], "hits": r["event_transfers_cost"] or 0, "chip": chips.get(ev),
            "captain": {"player_id": cap["player_id"], "name": names.get(cap["player_id"], ("?",))[0], "photo_code": names.get(cap["player_id"], (None, None))[1],
                        "team_code": names.get(cap["player_id"], (None, None, None))[2], "points": pts.get(cap["player_id"], 0),
                        "multiplier": cap["multiplier"]} if cap else None,
            "star": {"player_id": star["player_id"], "name": names.get(star["player_id"], ("?",))[0], "photo_code": names.get(star["player_id"], (None, None))[1],
                     "team_code": names.get(star["player_id"], (None, None, None))[2], "points": pts.get(star["player_id"], 0) * max(1, star["multiplier"])} if star else None,
        })

    cohort_total = {}
    entries = [r["entry_id"] for r in conn.execute("SELECT entry_id FROM cohort_entry WHERE cohort = ?", (COHORT,))]
    if entries:
        for r in conn.execute(
            f"SELECT event, AVG(total) AS t FROM cohort_gw WHERE entry_id IN ({','.join('?' * len(entries))}) AND total IS NOT NULL GROUP BY event", entries,
        ):
            cohort_total[r["event"]] = round(r["t"], 1)

    racers = []
    league = race_league(conn)
    if league is not None:
        for s in conn.execute("SELECT entry_id, entry_name, player_name FROM fpl_league_standing WHERE league_id = ?", (league,)).fetchall():
            if s["entry_id"] == entry_id:
                continue
            totals = {r["event"]: r["total_points"] for r in conn.execute(
                "SELECT event, total_points FROM rival_event WHERE entry_id = ? AND total_points IS NOT NULL", (s["entry_id"],))}
            if totals:
                racers.append({"entry_id": s["entry_id"], "name": s["player_name"] or s["entry_name"], "team": s["entry_name"], "totals": totals})
    league_name = conn.execute("SELECT name FROM fpl_league WHERE id = ?", (league,)).fetchone()["name"] if league else None

    def vs_avg(w):
        return w["points"] - (w["average"] or 0)

    ranked = [w for w in weeks if w["rank"]]
    moves = [(b["event"], (a["rank"] - b["rank"])) for a, b in zip(ranked, ranked[1:])]
    moments = {
        "best_week": max(weeks, key=vs_avg)["event"],
        "worst_week": min(weeks, key=vs_avg)["event"],
        "best_climb": max(moves, key=lambda m: m[1]) if moves else None,
        "worst_fall": min(moves, key=lambda m: m[1]) if moves else None,
        "best_captain": max((w for w in weeks if w["captain"]), key=lambda w: w["captain"]["points"] * w["captain"]["multiplier"])["event"],
        "worst_bench": max(weeks, key=lambda w: w["bench"] or 0)["event"],
    }
    return {
        "status": "ok", "entry_id": entry_id, "weeks": weeks, "cohort_total": cohort_total, "league": league_name, "racers": racers,
        "moments": moments, "season_average": round(mean(w["points"] for w in weeks), 1),
        "average_average": round(mean(w["average"] for w in weeks if w["average"] is not None), 1),
    }
