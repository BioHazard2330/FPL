"""THE MAP - every club's ground, the gameweek's ties as journeys from the away ground to the home one (great-circle
distance), each tie's kickoff, score, weather and referee, and the squad's players in it with their projection.

`event` defaults to the gameweek being played, else the next one."""
import math
from datetime import datetime, timedelta, timezone


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def build_map_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.ingestion.matchday_conditions import conditions_by_fixture
    from fpl_agent.optimization.week_plan import latest_week_plan, light_squad_state

    raw = (params or {}).get("event")
    raw = raw[0] if isinstance(raw, list) else raw
    conn = get_connection()
    try:
        now = datetime.now(timezone.utc)
        if raw:
            event = int(raw)
        else:
            live = conn.execute(
                "SELECT MIN(event) AS e FROM fixtures WHERE event IS NOT NULL AND kickoff_time <= ? AND kickoff_time >= ?",
                (now.isoformat(), (now - timedelta(hours=30)).isoformat()),
            ).fetchone()["e"]
            nxt = conn.execute(
                "SELECT MIN(event) AS e FROM fixtures WHERE event IS NOT NULL AND kickoff_time > ?", (now.isoformat(),),
            ).fetchone()["e"]
            event = live or nxt
        if event is None:
            return {"status": "no_event"}
        teams = {r["id"]: dict(r) for r in conn.execute("SELECT id, code, name, short_name FROM teams")}
        venues = {r["team_id"]: dict(r) for r in conn.execute("SELECT * FROM team_venue")}
        state = light_squad_state(conn)
        squad = set(state["squad_ids"]) if state else set()
        stored = latest_week_plan(conn)
        xp: dict[int, float] = {}
        if stored:
            for p in (stored[0].get("lineup_after") or {}).get("starting", []) + (stored[0].get("lineup_after") or {}).get("bench", []):
                xp[p["player_id"]] = p.get("xp") or p.get("median")
        mine_by_team: dict[int, list[dict]] = {}
        if squad:
            for r in conn.execute(
                f"SELECT id, web_name, team_id, code FROM players WHERE id IN ({','.join('?' * len(squad))})", sorted(squad),
            ):
                mine_by_team.setdefault(r["team_id"], []).append({"player_id": r["id"], "name": r["web_name"], "photo_code": r["code"], "xp": xp.get(r["id"])})
        rows = conn.execute("SELECT * FROM fixtures WHERE event = ? ORDER BY kickoff_time, id", (event,)).fetchall()
        cond = conditions_by_fixture(conn, [r["id"] for r in rows])
        fixtures = []
        for r in rows:
            h, a = venues.get(r["team_h"]), venues.get(r["team_a"])
            kick = r["kickoff_time"]
            started = bool(r["started"]) or (kick is not None and kick.replace("Z", "+00:00") <= now.isoformat())
            c = cond.get(r["id"]) or {}
            fixtures.append({
                "fixture_id": r["id"], "kickoff": kick, "home": r["team_h"], "away": r["team_a"],
                "score": [r["team_h_score"], r["team_a_score"]] if r["team_h_score"] is not None else None,
                "started": started, "finished": bool(r["finished"]),
                "km": round(_km((a["lat"], a["lon"]), (h["lat"], h["lon"]))) if h and a else None,
                "weather": {k: c.get(k) for k in ("forecast_temp", "forecast_precip_prob", "forecast_wind", "forecast_code")} if c else None,
                "referee": c.get("referee"), "ref_yellows_pm": c.get("ref_yellows_pm"),
                "yours": mine_by_team.get(r["team_h"], []) + mine_by_team.get(r["team_a"], []),
            })
        events = [x["event"] for x in conn.execute("SELECT DISTINCT event FROM fixtures WHERE event IS NOT NULL ORDER BY event")]
        return {
            "status": "ok", "event": event, "events": events,
            "clubs": [{"team_id": tid, "short": teams[tid]["short_name"], "name": teams[tid]["name"], "code": teams[tid]["code"],
                       "stadium": v["stadium"], "city": v["city"], "lat": v["lat"], "lon": v["lon"], "capacity": v["capacity"]}
                      for tid, v in venues.items() if tid in teams],
            "fixtures": fixtures,
        }
    finally:
        conn.close()
