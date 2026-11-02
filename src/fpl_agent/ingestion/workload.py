"""WORKLOAD - minutes and running per player across every competition.

FotMob's match details carry, per player, minutes, distance covered, running and sprinting distance, number of sprints,
top speed, touches and touches in the opposition box. Every finished Premier League match (`match_intelligence`) and every
finished cup or European match of a Premier League club (`cup_match`) is read once (`physical_match_read`) into
`player_physical`. Players are matched by FotMob id where a league match already linked it, else by name within the club.
`workload_block` sums the last 7, 14 and 28 days for a set of players: minutes split league and cup, distance, sprints,
and the latest top speed against his own average. Display only: congestion was measured inside the noise for league minutes."""
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

_logger = logging.getLogger(__name__)
PER_CYCLE = 40


def _val(s: dict | None):
    if not s:
        return None
    st = s.get("stat") or {}
    return st.get("value")


def parse_physical(payload: dict) -> list[dict]:
    """One row per player in a FotMob match-details payload: name, FotMob id, team name and the figures."""
    out = []
    teams = {}
    for side in ("homeTeam", "awayTeam"):
        t = (payload.get("general") or {}).get(side) or {}
        if t.get("id") is not None:
            teams[t["id"]] = t.get("name")
    for p in ((payload.get("content") or {}).get("playerStats") or {}).values():
        by_key = {}
        for grp in p.get("stats") or []:
            for s in (grp.get("stats") or {}).values():
                if s.get("key"):
                    by_key.setdefault(s["key"], s)
        minutes = _val(by_key.get("minutes_played"))
        if not minutes:
            continue
        out.append({
            "fotmob_id": str(p.get("id")), "name": p.get("name"), "team": teams.get(p.get("teamId")) or p.get("teamName"),
            "minutes": minutes, "distance_m": _val(by_key.get("physical_metrics_distance_covered")),
            "running_m": _val(by_key.get("physical_metrics_running")), "sprint_m": _val(by_key.get("physical_metrics_sprinting")),
            "sprints": _val(by_key.get("physical_metrics_number_of_sprints")), "top_speed": _val(by_key.get("physical_metrics_topspeed")),
            "touches": _val(by_key.get("touches")), "touches_box": _val(by_key.get("touches_opp_box")),
        })
    return out


def _due_matches(conn: sqlite3.Connection) -> list[tuple[str, str, str | None, list[int]]]:
    """(fotmob id, competition, kickoff, Premier League team ids in it) for finished matches not read yet."""
    rows = []
    for r in conn.execute(
        "SELECT mi.fotmob_match_id, mi.kickoff_utc, mi.home_team_id, mi.away_team_id FROM match_intelligence mi "
        "LEFT JOIN physical_match_read pr ON pr.fotmob_match_id = mi.fotmob_match_id WHERE mi.status = 'FULL_TIME' AND pr.fotmob_match_id IS NULL"
    ):
        rows.append((str(r["fotmob_match_id"]), "Premier League", r["kickoff_utc"], [r["home_team_id"], r["away_team_id"]]))
    for r in conn.execute(
        "SELECT cm.fotmob_match_id, cm.competition, cm.kickoff_utc, cm.team_id FROM cup_match cm "
        "LEFT JOIN physical_match_read pr ON pr.fotmob_match_id = cm.fotmob_match_id WHERE cm.status = 'FULL_TIME' AND pr.fotmob_match_id IS NULL"
    ):
        rows.append((str(r["fotmob_match_id"]), r["competition"], r["kickoff_utc"], [r["team_id"]]))
    return sorted(rows, key=lambda x: x[2] or "", reverse=True)


def sync_workload(conn: sqlite3.Connection, limit: int = PER_CYCLE, fetch=None) -> dict:
    from fpl_agent.ingestion.fotmob_source import fetch_match_details
    from fpl_agent.ingestion.predicted_lineups_source import match_player_in_team

    fetch = fetch or fetch_match_details
    by_fotmob = {str(r["fotmob_player_id"]): r["player_id"] for r in conn.execute(
        "SELECT DISTINCT fotmob_player_id, player_id FROM player_match_state WHERE player_id IS NOT NULL AND fotmob_player_id IS NOT NULL")}
    at = datetime.now(timezone.utc).isoformat()
    read = stored = failed = 0
    for mid, comp, kick, team_ids in _due_matches(conn)[:limit]:
        try:
            rows = parse_physical(fetch(mid))
        except Exception as e:
            _logger.warning("workload: match %s failed: %s", mid, e)
            failed += 1
            continue
        n = 0
        for r in rows:
            pid = by_fotmob.get(r["fotmob_id"])
            if pid is None:
                for t in team_ids:
                    pid = match_player_in_team(conn, t, r["name"] or "")
                    if pid is not None:
                        break
            if pid is None:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO player_physical (fotmob_match_id, player_id, competition, kickoff_utc, minutes, distance_m, running_m, "
                "sprint_m, sprints, top_speed, touches, touches_box, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mid, pid, comp, kick, r["minutes"], r["distance_m"], r["running_m"], r["sprint_m"], r["sprints"], r["top_speed"],
                 r["touches"], r["touches_box"], at),
            )
            n += 1
        conn.execute("INSERT OR REPLACE INTO physical_match_read (fotmob_match_id, players, retrieved_at) VALUES (?, ?, ?)", (mid, n, at))
        read += 1
        stored += n
    conn.commit()
    return {"matches": read, "players": stored, "failed": failed, "pending": max(0, len(_due_matches(conn)))}


def workload_block(conn: sqlite3.Connection, player_ids: list[int], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    if not player_ids:
        return []
    marks = ",".join("?" * len(player_ids))
    since = (now - timedelta(days=28)).isoformat()
    rows = conn.execute(
        f"SELECT * FROM player_physical WHERE player_id IN ({marks}) AND replace(kickoff_utc, 'Z', '+00:00') >= ? ORDER BY kickoff_utc",
        (*player_ids, since),
    ).fetchall()
    speed_avg = {r["player_id"]: r["s"] for r in conn.execute(
        f"SELECT player_id, AVG(top_speed) AS s FROM player_physical WHERE player_id IN ({marks}) AND top_speed IS NOT NULL GROUP BY player_id", player_ids)}
    names = {r["id"]: (r["web_name"], r["code"], r["team_code"]) for r in conn.execute(
        f"SELECT p.id, p.web_name, p.code, t.code AS team_code FROM players p JOIN teams t ON t.id = p.team_id WHERE p.id IN ({marks})", player_ids)}
    out = []
    for pid in player_ids:
        mine = [r for r in rows if r["player_id"] == pid]

        def window(days: int, cup: bool | None = None) -> int:
            lo = (now - timedelta(days=days)).isoformat()
            return sum(r["minutes"] or 0 for r in mine if (r["kickoff_utc"] or "").replace("Z", "+00:00") >= lo
                       and (cup is None or (r["competition"] != "Premier League") == cup))

        last = mine[-1] if mine else None
        out.append({
            "player_id": pid, "name": names.get(pid, ("?",))[0], "photo_code": names.get(pid, (None, None))[1], "team_code": names.get(pid, (None, None, None))[2],
            "minutes_7": window(7), "minutes_14": window(14), "minutes_28": window(28), "cup_minutes_14": window(14, True), "league_minutes_14": window(14, False),
            "matches_14": sum(1 for r in mine if (r["kickoff_utc"] or "").replace("Z", "+00:00") >= (now - timedelta(days=14)).isoformat()),
            "distance_14_km": round(sum((r["distance_m"] or 0) for r in mine if (r["kickoff_utc"] or "").replace("Z", "+00:00") >= (now - timedelta(days=14)).isoformat()) / 1000, 1),
            "last": {"competition": last["competition"], "kickoff": last["kickoff_utc"], "minutes": last["minutes"], "distance_km": round((last["distance_m"] or 0) / 1000, 1),
                     "sprints": last["sprints"], "top_speed": last["top_speed"], "touches_box": last["touches_box"]} if last else None,
            "top_speed_avg": round(speed_avg[pid], 1) if speed_avg.get(pid) else None,
            "matches": [{"competition": r["competition"], "kickoff": r["kickoff_utc"], "minutes": r["minutes"]} for r in mine],
        })
    return out
