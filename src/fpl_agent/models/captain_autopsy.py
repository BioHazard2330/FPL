"""THE ARMBAND, gameweek by gameweek: what the captain scored, what the best
armband in the same eleven would have scored, and how much of the captain's
return was the chances against luck.

One row per settled gameweek with stored picks. The captain's doubled (or
tripled) points are set against the highest-scoring player of the same eleven
that gameweek, so the cost is what the armband left on the table in points, not
a judgement of the choice: the best armband in hindsight is nearly always
someone nobody picked. The deserved column splits the captain's own points the
way the luck audit does (finishing, final pass, clean sheet, goals against
against what the chances said), so a flat return from a sound pick shows up as
owed points rather than a wrong call. The deserved best-in-eleven is the same
reading for the alternative.

It describes what happened. It does not say the pick was right or wrong when
the choice was made; the projections at the time are in the week plan's
captain ladder."""
import sqlite3

from fpl_agent.models.luck_audit import _scoring_points, player_gw_luck
from fpl_agent.models.rules import current_season


def captain_autopsy(conn: sqlite3.Connection, entry_id: int) -> list[dict]:
    season = current_season(conn)
    pts = _scoring_points(conn, season)
    picks = conn.execute(
        "SELECT event, player_id, squad_slot, multiplier, is_captain, active_chip FROM my_team_picks WHERE entry_id=? ORDER BY event, squad_slot",
        (entry_id,),
    ).fetchall()
    by_event: dict[int, list[sqlite3.Row]] = {}
    for r in picks:
        by_event.setdefault(r["event"], []).append(r)
    out = []
    for event, rows in sorted(by_event.items()):
        stats = {
            r["player_id"]: dict(r) for r in conn.execute(
                "SELECT g.*, et.singular_name_short AS position, p.web_name FROM player_gw_stats g "
                "JOIN players p ON p.id = g.player_id JOIN element_types et ON et.id = p.element_type "
                "WHERE g.season=? AND g.event=?", (season, event),
            )
        }
        captain = next((r for r in rows if r["is_captain"]), None)
        if captain is None or captain["player_id"] not in stats:
            continue
        xi = [r for r in rows if r["multiplier"] >= 1 and r["player_id"] in stats]
        if not xi:
            continue

        def deserved(pid: int) -> tuple[float, float]:
            s = stats[pid]
            gp, ap, cp, kp = pts[s["position"]]
            luck = player_gw_luck(s, gp, ap, cp, kp).total if s["minutes"] > 0 else 0.0
            return s["total_points"], s["total_points"] - luck

        mult = max(captain["multiplier"], 2)
        cap_actual, cap_deserved = deserved(captain["player_id"])
        scored = {r["player_id"]: deserved(r["player_id"]) for r in xi}
        best_actual = max(scored, key=lambda p: scored[p][0])
        best_deserved = max(scored, key=lambda p: scored[p][1])
        out.append({
            "event": event, "multiplier": mult, "chip": captain["active_chip"],
            "captain": {"player_id": captain["player_id"], "name": stats[captain["player_id"]]["web_name"],
                        "actual": cap_actual, "deserved": round(cap_deserved, 1)},
            "best_actual": {"player_id": best_actual, "name": stats[best_actual]["web_name"], "actual": scored[best_actual][0]},
            "best_deserved": {"player_id": best_deserved, "name": stats[best_deserved]["web_name"], "deserved": round(scored[best_deserved][1], 1)},
            "cost": round((scored[best_actual][0] - cap_actual) * (mult - 1), 1),
            "owed": round((cap_deserved - cap_actual) * (mult - 1), 1),
        })
    return out
