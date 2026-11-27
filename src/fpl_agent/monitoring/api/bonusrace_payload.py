"""The bonus race and defensive contributions, live (2026-11-27, the manager: "defcon and bonus - yes").

For every match of the live gameweek that has kicked off: the top of its BPS table with the provisional 3-2-1, every
squad player in it with his BPS and how far he is from the last bonus place, and what one goal or assist would add to
his BPS by FPL's published scoring (goal 24 forward / 18 midfielder / 12 defender or keeper, assist 9). For every squad
player the defensive-contribution rule applies to: his count against his position's threshold (FPL's live
`defensive_contribution`). Read from FPL's live endpoint through the same fetch the live snapshot uses, cached 20s."""
import threading
import time

GOAL_BPS = {"FWD": 24, "MID": 18, "DEF": 12, "GKP": 12}
ASSIST_BPS = 9
_CACHE: dict[str, tuple[float, dict]] = {}
_LOCK = threading.Lock()
TTL = 20.0


def build_bonusrace_payload(ctx=None, params: dict | None = None) -> dict:
    with _LOCK:
        hit = _CACHE.get("race")
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
    from fpl_agent.database.connection import get_connection

    conn = get_connection()
    try:
        out = _build(conn)
    finally:
        conn.close()
    with _LOCK:
        _CACHE["race"] = (time.time(), out)
    return out


def _build(conn) -> dict:
    from fpl_agent.models.live_bonus import compute_live_bonus
    from fpl_agent.monitoring.dashboard.context import maybe_fetch_live_payload

    payload = maybe_fetch_live_payload(conn)
    if not payload:
        return {"status": "none"}
    rows = compute_live_bonus(conn, payload)
    last = conn.execute("SELECT MAX(event) FROM my_team_picks").fetchone()[0]
    picks = {r[0]: r[1] for r in conn.execute("SELECT player_id, squad_slot FROM my_team_picks WHERE event = ?", (last,))}
    fixtures = {r[0]: r for r in conn.execute(
        "SELECT f.id, th.short_name, ta.short_name, th.code, ta.code, f.finished, f.team_h_score, f.team_a_score, f.kickoff_time "
        "FROM fixtures f JOIN teams th ON th.id = f.team_h JOIN teams ta ON ta.id = f.team_a")}
    by_fixture: dict[int, list] = {}
    for r in rows:
        by_fixture.setdefault(r.fixture_id, []).append(r)
    matches = []
    for fid, group in by_fixture.items():
        group.sort(key=lambda r: -r.bps)
        f = fixtures.get(fid)
        line = min((r.bps for r in group if r.provisional_bonus), default=None)

        def row(r):
            return {"player_id": r.player_id, "name": r.web_name, "team_code": r.team_code, "position": r.position, "bps": r.bps,
                    "bonus": r.confirmed_bonus if r.confirmed_bonus is not None else r.provisional_bonus,
                    "confirmed": r.confirmed_bonus is not None, "mine": r.player_id in picks,
                    "starting": picks.get(r.player_id, 99) <= 11, "minutes": r.minutes,
                    "to_bonus": None if (r.provisional_bonus or line is None) else line - r.bps + 1,
                    "goal_adds": GOAL_BPS.get(r.position, 12), "assist_adds": ASSIST_BPS}
        top = [row(r) for r in group[:5]]
        mine = [row(r) for r in group[5:] if r.player_id in picks]
        matches.append({
            "fixture": fid, "home": f[1] if f else "?", "away": f[2] if f else "?", "home_code": f[3] if f else None,
            "away_code": f[4] if f else None, "finished": bool(f[5]) if f else False,
            "score": [f[6], f[7]] if f else [None, None], "kickoff": f[8] if f else None,
            "bonus_line": line, "top": top, "yours_below": mine, "has_yours": any(x["mine"] for x in top) or bool(mine),
        })
    matches.sort(key=lambda m: (not m["has_yours"], m["finished"], m["kickoff"] or ""), reverse=False)
    defcon = []
    seen = set()
    for r in rows:
        if r.player_id in picks and r.defcon_threshold and r.player_id not in seen:
            seen.add(r.player_id)
            defcon.append({"player_id": r.player_id, "name": r.web_name, "position": r.position, "team_code": r.team_code,
                           "count": r.defensive_contribution, "threshold": r.defcon_threshold, "reached": r.defcon_reached,
                           "minutes": r.minutes, "starting": picks.get(r.player_id, 99) <= 11})
    defcon.sort(key=lambda d: (not d["starting"], -(d["count"] / d["threshold"])))
    return {"status": "ok", "matches": matches, "defcon": defcon}


build_bonusrace_payload.needs_context = False
