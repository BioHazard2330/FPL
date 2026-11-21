"""Every fixture of the gameweek in play (or the next one before its deadline), in kickoff order, with the live state where
the match feed has it (`match_intelligence`: status, minute, score) and FPL's otherwise. The Live screen's match rail."""
from datetime import datetime, timezone


def build_gwfixtures_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection

    conn = get_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        row = conn.execute("SELECT id FROM events WHERE deadline_time <= ? ORDER BY deadline_time DESC LIMIT 1", (now,)).fetchone()
        event = row["id"] if row else None
        if event is None or conn.execute("SELECT finished FROM events WHERE id = ?", (event,)).fetchone()["finished"]:
            nxt = conn.execute("SELECT id FROM events WHERE deadline_time > ? ORDER BY deadline_time LIMIT 1", (now,)).fetchone()
            event = nxt["id"] if nxt else event
        teams = {r["id"]: r for r in conn.execute("SELECT id, short_name, code FROM teams")}
        live = {r["fpl_fixture_id"]: r for r in conn.execute(
            "SELECT fpl_fixture_id, id, status, live_minute, home_score, away_score FROM match_intelligence WHERE fpl_fixture_id IS NOT NULL AND competition LIKE '%Premier%'")}
        out = []
        for f in conn.execute("SELECT id, kickoff_time, team_h, team_a, team_h_score, team_a_score, started, finished FROM fixtures WHERE event = ? ORDER BY kickoff_time, id", (event,)):
            m = live.get(f["id"])
            if m is not None and m["status"] in ("LIVE", "HALFTIME"):
                status, score = m["status"], [m["home_score"], m["away_score"]]
            elif f["finished"] or (m is not None and m["status"] == "FULL_TIME"):
                status = "FULL_TIME"
                score = [f["team_h_score"], f["team_a_score"]] if f["team_h_score"] is not None else [m["home_score"], m["away_score"]] if m else [None, None]
            elif f["started"]:
                status, score = "LIVE", [f["team_h_score"], f["team_a_score"]]
            else:
                status, score = "PRE", [None, None]
            h, a = teams[f["team_h"]], teams[f["team_a"]]
            out.append({"fixture_id": f["id"], "match_id": m["id"] if m else None, "kickoff": f["kickoff_time"], "status": status,
                        "minute": m["live_minute"] if m and status in ("LIVE", "HALFTIME") else None, "score": score,
                        "home": {"team_id": h["id"], "short": h["short_name"], "code": h["code"]}, "away": {"team_id": a["id"], "short": a["short_name"], "code": a["code"]}})
        return {"event": event, "fixtures": out}
    finally:
        conn.close()


build_gwfixtures_payload.needs_context = False
