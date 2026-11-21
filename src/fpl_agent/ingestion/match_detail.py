"""Every player's full match record from FotMob's public match details: the whole `playerStats` block (passes, final-third
entries, line-breaking passes, dribbles, duels, tackles, interceptions, recoveries, clearances, corners taken, crosses,
physical...) and where each starter lined up on the formation grid (`horizontalLayout`: x is depth from his own goal,
0.1 goalkeeper to 0.87 striker; y is width, above 0.5 the right side). Read once per finished league match into
`player_match_detail` (migration 0067); `role` is the slot the grid puts him in (`role_for`).

FotMob players are matched to FPL through `player_match_state.fotmob_player_id` (written by `fotmob_source.sync_match`
for every listed player); a player FotMob lists that the sync never matched is stored with no FPL id."""
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

ROLES = ("GK", "CB", "FB", "WB", "DM", "CM", "AM", "W", "ST")


def role_for(x: float | None, y: float | None, back_line: int) -> str | None:
    """The slot on the formation grid. `back_line` is the number of outfielders in the deepest line (3 means wide
    midfielders are wing-backs)."""
    if x is None or y is None:
        return None
    wide = y <= 0.22 or y >= 0.78
    if x <= 0.15:
        return "GK"
    if x < 0.4:
        return "FB" if wide else "CB"
    if x < 0.6:
        if wide:
            return "WB" if back_line <= 3 else "W"
        return "DM" if x < 0.5 else "CM"
    if x < 0.8:
        return "W" if wide else "AM"
    return "ST"


def _flat(stats: list[dict]) -> dict:
    out: dict = {}
    for group in stats or []:
        for label, s in (group.get("stats") or {}).items():
            key = s.get("key") or label
            stat = s.get("stat") or {}
            value = stat.get("value")
            if value is None or stat.get("type") == "boolean":
                continue
            out[key] = value
            if stat.get("total") is not None:
                out[f"{key}_total"] = stat["total"]
    return out


def parse(details: dict) -> list[dict]:
    content = details.get("content") or {}
    lineup = content.get("lineup") or {}
    stats = content.get("playerStats") or {}
    rows: dict[int, dict] = {}
    for side in ("homeTeam", "awayTeam"):
        team = lineup.get(side) or {}
        starters = team.get("starters") or []
        layouts = [(s.get("horizontalLayout") or {}).get("x") for s in starters]
        outfield = sorted(x for x in layouts if x is not None and x > 0.15)
        back = sum(1 for x in outfield if outfield and abs(x - outfield[0]) < 0.03)
        for s in starters:
            lay = s.get("horizontalLayout") or {}
            rows[int(s["id"])] = {"fotmob_player_id": int(s["id"]), "started": 1, "line_x": lay.get("x"), "line_y": lay.get("y"),
                                  "role": role_for(lay.get("x"), lay.get("y"), back), "formation": team.get("formation"), "stats": {}}
        for s in team.get("subs") or []:
            rows.setdefault(int(s["id"]), {"fotmob_player_id": int(s["id"]), "started": 0, "line_x": None, "line_y": None,
                                           "role": None, "formation": team.get("formation"), "stats": {}})
    for pid, p in stats.items():
        try:
            fid = int(p.get("id") or pid)
        except (TypeError, ValueError):
            continue
        row = rows.setdefault(fid, {"fotmob_player_id": fid, "started": 0, "line_x": None, "line_y": None, "role": None, "formation": None, "stats": {}})
        row["stats"] = _flat(p.get("stats"))
    return [r for r in rows.values() if r["stats"]]


def store(conn: sqlite3.Connection, match_id: int, rows: list[dict]) -> int:
    ids = {int(r["fotmob_player_id"]): (r["player_id"], r["team_id"]) for r in conn.execute(
        "SELECT fotmob_player_id, player_id, team_id FROM player_match_state WHERE match_id = ? AND fotmob_player_id IS NOT NULL", (match_id,))}
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        pid, tid = ids.get(r["fotmob_player_id"], (None, None))
        conn.execute(
            "INSERT INTO player_match_detail (match_id, fotmob_player_id, player_id, team_id, started, role, line_x, line_y, formation, stats_json, retrieved_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(match_id, fotmob_player_id) DO UPDATE SET player_id=excluded.player_id, team_id=excluded.team_id, "
            "started=excluded.started, role=excluded.role, line_x=excluded.line_x, line_y=excluded.line_y, formation=excluded.formation, "
            "stats_json=excluded.stats_json, retrieved_at=excluded.retrieved_at",
            (match_id, r["fotmob_player_id"], pid, tid, r["started"], r["role"], r["line_x"], r["line_y"], r["formation"], json.dumps(r["stats"]), now),
        )
    conn.commit()
    return len(rows)


def remap(conn: sqlite3.Connection) -> int:
    """Fill FPL ids for stored rows whose player the lineup sync matched later."""
    cur = conn.execute(
        "UPDATE player_match_detail SET (player_id, team_id) = (SELECT s.player_id, s.team_id FROM player_match_state s "
        "WHERE s.match_id = player_match_detail.match_id AND CAST(s.fotmob_player_id AS INTEGER) = player_match_detail.fotmob_player_id) "
        "WHERE player_id IS NULL AND EXISTS (SELECT 1 FROM player_match_state s WHERE s.match_id = player_match_detail.match_id "
        "AND CAST(s.fotmob_player_id AS INTEGER) = player_match_detail.fotmob_player_id)"
    )
    conn.commit()
    return cur.rowcount


def missing(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT mi.id, mi.fotmob_match_id FROM match_intelligence mi WHERE mi.status = 'FULL_TIME' AND mi.competition LIKE '%Premier%' "
        "AND mi.kickoff_utc < ? AND NOT EXISTS (SELECT 1 FROM player_match_detail d WHERE d.match_id = mi.id) ORDER BY mi.kickoff_utc",
        (datetime.now(timezone.utc).isoformat(),),
    ).fetchall()


def sync_details(conn: sqlite3.Connection, limit: int = 40, pause: float = 0.4) -> dict:
    """Read the details of finished league matches not yet stored, oldest first."""
    from fpl_agent.ingestion.fotmob_source import fetch_match_details

    done, players, failed = 0, 0, 0
    for m in missing(conn)[:limit]:
        try:
            rows = parse(fetch_match_details(str(m["fotmob_match_id"])))
        except Exception:
            logger.warning("match detail fetch failed for %s", m["fotmob_match_id"], exc_info=True)
            failed += 1
            continue
        if rows:
            players += store(conn, m["id"], rows)
            done += 1
        time.sleep(pause)
    return {"matches": done, "players": players, "failed": failed, "remapped": remap(conn)}


def stats_for(conn: sqlite3.Connection, player_ids: list[int] | None = None, team_id: int | None = None) -> list[dict]:
    where, args = ["d.player_id IS NOT NULL"], []
    if player_ids:
        where.append(f"d.player_id IN ({','.join('?' * len(player_ids))})")
        args += list(player_ids)
    if team_id is not None:
        where.append("d.team_id = ?")
        args.append(team_id)
    return [
        {"match_id": r["match_id"], "kickoff": r["kickoff_utc"], "player_id": r["player_id"], "team_id": r["team_id"], "started": r["started"],
         "role": r["role"], "x": r["line_x"], "y": r["line_y"], "formation": r["formation"], "stats": json.loads(r["stats_json"])}
        for r in conn.execute(
            f"SELECT d.*, mi.kickoff_utc FROM player_match_detail d JOIN match_intelligence mi ON mi.id = d.match_id WHERE {' AND '.join(where)} ORDER BY mi.kickoff_utc", args)
    ]
