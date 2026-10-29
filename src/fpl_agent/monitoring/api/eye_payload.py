"""THE EYE JOURNAL screen: the players worth a note after the last finished gameweek (the squad and the plan's targets)
with what they did, the notes already made, and the journal's scorecard (`models/eye_journal`)."""


def build_eye_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.ingestion.my_team import get_my_team_entry_id
    from fpl_agent.models.eye_journal import RATINGS, TAGS, latest_reads, notes_for_event, scorecard
    from fpl_agent.models.rules import current_season
    from fpl_agent.optimization.week_plan import latest_week_plan, light_squad_state

    conn = get_connection()
    try:
        entry = get_my_team_entry_id(conn)
        row = conn.execute("SELECT MAX(event) AS e FROM my_team_gw_summary WHERE entry_id = ?", (entry,)).fetchone() if entry else None
        event = int((params or {}).get("event") or (row["e"] if row and row["e"] else 0)) or None
        if event is None:
            return {"status": "none"}
        state = light_squad_state(conn)
        squad = list(state["squad_ids"]) if state else []
        targets: dict[int, str] = {}
        stored = latest_week_plan(conn)
        if stored:
            plan = stored[0]
            for m in plan.get("moves", []) + plan.get("declined", []):
                targets.setdefault(m["into"]["player_id"], f"GW{plan['event']}")
            for w in (plan.get("road_ahead") or {}).get("weeks", []):
                for m in w.get("moves", []):
                    if m.get("in_id"):
                        targets.setdefault(m["in_id"], f"GW{w['event']}")
        ids = squad + [t for t in targets if t not in squad]
        if not ids:
            return {"status": "none"}
        season = current_season(conn)
        marks = ",".join("?" * len(ids))
        info = {r["id"]: dict(r) for r in conn.execute(
            "SELECT p.id, p.web_name AS name, p.code AS photo_code, t.short_name AS team_short, t.code AS team_code, "
            "et.singular_name_short AS position FROM players p JOIN teams t ON t.id = p.team_id JOIN element_types et "
            f"ON et.id = p.element_type WHERE p.id IN ({marks})", ids)}
        stats = {r["player_id"]: dict(r) for r in conn.execute(
            "SELECT player_id, minutes, goals, assists, bonus, xg, xa, total_points, defensive_contribution, saves FROM player_gw_stats "
            f"WHERE season = ? AND event = ? AND player_id IN ({marks})", [season, event] + ids)}
        notes = notes_for_event(conn, event)
        reads = latest_reads(conn)
        order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
        players = []
        for pid in ids:
            i = info.get(pid)
            if not i:
                continue
            players.append({
                **{k: v for k, v in i.items() if k != "id"}, "player_id": pid, "group": "squad" if pid in squad else "target",
                "target_when": targets.get(pid), "gw": stats.get(pid), "note": notes.get(pid), "current_read": reads.get(pid),
            })
        players.sort(key=lambda p: (p["group"] != "squad", order.get(p["position"], 9), -((p["gw"] or {}).get("total_points") or 0)))
        return {
            "status": "ok", "event": event, "players": players, "tags": list(TAGS),
            "ratings": [{"value": k, "label": v} for k, v in RATINGS.items()], "scorecard": scorecard(conn),
            "events": [r[0] for r in conn.execute("SELECT DISTINCT event FROM my_team_gw_summary ORDER BY event")],
        }
    finally:
        conn.close()


build_eye_payload.needs_context = False  # type: ignore[attr-defined]
