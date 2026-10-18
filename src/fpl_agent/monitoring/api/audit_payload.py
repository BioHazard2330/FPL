"""THE AUDIT screen: whose points were luck, and what each match deserved.

Three reads over stored data (no projections, no dashboard context):
- the regression radar: players running hot or cold against their own chances,
  over the season and over the last four gameweeks, with the squad flagged;
- your squad's luck, player by player;
- the matches of one gameweek rebuilt from their shots (cumulative xG against
  the clock and the result those chances deserved).
See `models/luck_audit.py` and `models/match_rebuild.py` for the arithmetic and
what it does not claim."""
from fpl_agent.monitoring.api.photos import attach_photo_codes
from fpl_agent.monitoring.dashboard.context import DashboardContext

_MIN_MINUTES = 270
_RADAR_ROWS = 8


def _decorate(conn, rows: list[dict], squad: set[int]) -> list[dict]:
    if not rows:
        return rows
    ids = [r["player_id"] for r in rows]
    marks = ",".join("?" * len(ids))
    info = {
        r["player_id"]: r for r in conn.execute(
            f"SELECT p.id AS player_id, s.now_cost, "
            f"(SELECT selected_by_percent FROM player_ownership_history WHERE player_id = p.id AND valid_until IS NULL) AS owned "
            f"FROM players p LEFT JOIN player_stats_snapshot s ON s.id = (SELECT MAX(id) FROM player_stats_snapshot WHERE player_id = p.id) "
            f"WHERE p.id IN ({marks})", ids,
        )
    }
    out = []
    for r in rows:
        i = info.get(r["player_id"])
        out.append({
            **r, "mine": r["player_id"] in squad,
            "price": i["now_cost"] / 10 if i and i["now_cost"] is not None else None, "owned": i["owned"] if i else None,
        })
    return out


def build_audit_payload(ctx: DashboardContext, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.luck_audit import season_luck
    from fpl_agent.models.match_rebuild import rebuild_match
    from fpl_agent.optimization.week_plan import light_squad_state

    params = params or {}
    conn = get_connection()
    try:
        state = light_squad_state(conn)
        squad = set(state["squad_ids"]) if state else set()

        events = [r["event"] for r in conn.execute(
            "SELECT DISTINCT f.event FROM match_intelligence mi JOIN fixtures f ON f.id = mi.fpl_fixture_id "
            "WHERE mi.status='FULL_TIME' AND f.event IS NOT NULL ORDER BY f.event")]
        try:
            event = int(params["event"]) if "event" in params else (events[-1] if events else None)
        except ValueError:
            raise LookupError("event must be a gameweek number") from None

        def radar(last_n: int | None) -> dict:
            rows = [r for r in season_luck(conn, last_n) if r["minutes"] >= (_MIN_MINUTES if last_n is None else 180)]
            hot = sorted(rows, key=lambda r: -r["z"])[:_RADAR_ROWS]
            cold = sorted(rows, key=lambda r: r["z"])[:_RADAR_ROWS]
            return {"hot": _decorate(conn, hot, squad), "cold": _decorate(conn, cold, squad)}

        season_rows = season_luck(conn)
        squad_rows = _decorate(conn, sorted((r for r in season_rows if r["player_id"] in squad), key=lambda r: -r["z"]), squad)

        matches = []
        if event is not None:
            ids = [r["id"] for r in conn.execute(
                "SELECT mi.id FROM match_intelligence mi JOIN fixtures f ON f.id = mi.fpl_fixture_id "
                "WHERE mi.status='FULL_TIME' AND f.event = ? ORDER BY mi.kickoff_utc", (event,))]
            matches = [m for m in (rebuild_match(conn, i) for i in ids) if m is not None]

        from fpl_agent.ingestion.my_team import get_my_team_entry_id
        from fpl_agent.models.captain_autopsy import captain_autopsy

        entry = get_my_team_entry_id(conn)
        armband = captain_autopsy(conn, entry) if entry is not None else []
        payload = {
            "armband": armband,
            "event": event, "events": events, "radar_season": radar(None), "radar_recent": radar(4),
            "squad": squad_rows, "matches": matches,
            "thresholds": {"min_minutes": _MIN_MINUTES, "recent_gameweeks": 4},
        }
        return attach_photo_codes(conn, payload)
    finally:
        conn.close()


build_audit_payload.needs_context = False
