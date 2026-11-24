"""The verdict board (`models/verdict.py`): every player with league minutes judged on expected points, real returns,
value, track record against the model, fixtures and security, with the squad first; `?position=DEF` narrows it."""


def build_verdicts_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.verdict import WEIGHTS, build
    from fpl_agent.monitoring.api.photos import attach_photo_codes
    from fpl_agent.optimization.week_plan import light_squad_state

    params = params or {}
    conn = get_connection()
    try:
        if params.get("player"):
            pid = int(params["player"])
            one = build(conn, [pid]).get(pid)
            if one is not None:
                code = conn.execute("SELECT t.code FROM players p JOIN teams t ON t.id = p.team_id WHERE p.id = ?", (pid,)).fetchone()
                one["team_code"] = code[0] if code else None
            return attach_photo_codes(conn, {"weights": WEIGHTS, "player": one})
        state = light_squad_state(conn)
        squad = list(state["squad_ids"]) if state else []
        everyone = build(conn, None, with_checks=False)
        mine = build(conn, squad, with_checks=True)
        rows = [v for v in everyone.values() if v["player_id"] not in mine] + list(mine.values())
        pos = params.get("position")
        if pos:
            rows = [r for r in rows if r["position"] == pos]
        for r in rows:
            r["mine"] = r["player_id"] in mine
        team_codes = {r[0]: r[1] for r in conn.execute("SELECT short_name, code FROM teams")}
        for r in rows:
            r["team_code"] = team_codes.get(r["team"])
        rows.sort(key=lambda r: (-(r["score"] or 0)))
        return attach_photo_codes(conn, {"weights": WEIGHTS, "squad": sorted(mine.values(), key=lambda r: -(r["score"] or 0)), "players": rows})
    finally:
        conn.close()


build_verdicts_payload.needs_context = False
