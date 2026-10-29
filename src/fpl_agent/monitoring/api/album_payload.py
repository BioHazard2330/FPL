"""THE SQUAD ALBUM - each player of the squad as a printed sticker: club and kit, the season's real numbers, his scouting
profile and best and worst measures, the football read's verdict and the lines that carry, what the plan intends for him,
and the top ten thousand's ownership of him. Everything is an existing reading (`football_read`, `scouting_report`,
the stored week plan, `player_gw_stats`, the top-10k sample); this only gathers it per player."""
import logging

_logger = logging.getLogger(__name__)


def _plan_fate(plan: dict | None, pid: int) -> dict | None:
    if plan is None:
        return None
    for m in plan.get("moves", []):
        if m["out"]["player_id"] == pid:
            return {"kind": "sell", "when": f"GW{plan['event']}", "for": m["into"]["name"]}
    for w in (plan.get("road_ahead") or {}).get("weeks", [])[1:]:
        for m in w.get("moves", []):
            if m.get("out_id") == pid:
                return {"kind": "sell", "when": f"GW{w['event']}", "for": m["into"]}
    after = plan.get("lineup_after") or {}
    if after.get("captain_id") == pid:
        return {"kind": "captain", "when": f"GW{plan['event']}"}
    if any(p["player_id"] == pid for p in after.get("bench", [])):
        return {"kind": "bench", "when": f"GW{plan['event']}"}
    return {"kind": "keep", "when": None}


def build_album_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.football_read import football_read
    from fpl_agent.models.rules import current_season
    from fpl_agent.models.scouting import scouting_report
    from fpl_agent.optimization.week_plan import latest_week_plan, light_squad_state

    conn = get_connection()
    try:
        state = light_squad_state(conn)
        if not state:
            return {"status": "no_squad"}
        ids = list(state["squad_ids"])
        stored = latest_week_plan(conn)
        plan = stored[0] if stored else None
        season = current_season(conn)
        marks = ",".join("?" * len(ids))
        info = {r["id"]: dict(r) for r in conn.execute(
            "SELECT p.id, p.web_name AS name, p.first_name, p.second_name, p.code AS photo_code, p.status, p.news, t.name AS team_name, "
            "t.short_name AS team_short, t.code AS team_code, et.singular_name_short AS position, "
            "(SELECT now_cost FROM player_stats_snapshot s WHERE s.player_id = p.id ORDER BY retrieved_at DESC LIMIT 1) AS cost "
            f"FROM players p JOIN teams t ON t.id = p.team_id JOIN element_types et ON et.id = p.element_type WHERE p.id IN ({marks})", ids)}
        totals = {r["player_id"]: dict(r) for r in conn.execute(
            "SELECT player_id, SUM(total_points) AS points, SUM(minutes) AS minutes, SUM(goals) AS goals, SUM(assists) AS assists, "
            "SUM(bonus) AS bonus, SUM(xg) AS xg, SUM(xa) AS xa, SUM(starts) AS starts FROM player_gw_stats "
            f"WHERE season = ? AND player_id IN ({marks}) GROUP BY player_id", [season] + ids)}
        sample = {r["player_id"]: r["eo"] for r in conn.execute(
            "SELECT player_id, sum_multiplier * 1.0 / sample_size AS eo FROM player_sample_ownership_history WHERE season = ? AND event = "
            f"(SELECT MAX(event) FROM player_sample_ownership_history WHERE season = ?) AND player_id IN ({marks})", [season, season] + ids)}
        xp = {}
        if plan:
            for p in (plan.get("lineup_after") or {}).get("starting", []) + (plan.get("lineup_after") or {}).get("bench", []):
                xp[p["player_id"]] = p.get("xp")
        order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
        stickers = []
        for pid in ids:
            i = info.get(pid)
            if i is None:
                continue
            read = None
            try:
                read = football_read(conn, pid)
            except Exception:
                _logger.exception("album: football read failed for %s", pid)
            scout = None
            try:
                scout = scouting_report(conn, pid)
            except Exception:
                _logger.exception("album: scouting failed for %s", pid)
            t = totals.get(pid, {})
            stickers.append({
                "player_id": pid, "name": i["name"], "full_name": " ".join(x for x in (i["first_name"], i["second_name"]) if x),
                "photo_code": i["photo_code"], "team_name": i["team_name"], "team_short": i["team_short"], "team_code": i["team_code"],
                "position": i["position"], "price": (i["cost"] or 0) / 10, "status": i["status"], "news": i["news"],
                "season": {k: t.get(k) for k in ("points", "minutes", "goals", "assists", "bonus", "xg", "xa", "starts")},
                "xp": xp.get(pid), "top10k_eo": round(sample[pid], 2) if pid in sample else None,
                "verdict": read["verdict"] if read else None,
                "lines": [
                    {"topic": ln["topic"], "weight": ln["weight"], "lean": ln["lean"], "text": ln["text"]}
                    for ln in (read or {}).get("lines", []) if ln["weight"] in ("carries", "noise") or ln["lean"]
                ][:4],
                "profile": (scout or {}).get("profile") or [],
                "best": [{"label": m["label"], "display": m["display"], "percentile": m["percentile"]} for m in (scout or {}).get("strengths", [])[:2]],
                "worst": [{"label": m["label"], "display": m["display"], "percentile": m["percentile"]} for m in (scout or {}).get("weaknesses", [])[:1]],
                "fate": _plan_fate(plan, pid),
            })
        stickers.sort(key=lambda s: (order.get(s["position"], 9), -(s["xp"] or 0)))
        return {"status": "ok", "event": plan["event"] if plan else None, "stickers": stickers}
    finally:
        conn.close()


build_album_payload.needs_context = False  # type: ignore[attr-defined]
