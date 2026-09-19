"""THE ATLAS - every real shot in the league this season, as one payload.

`match_shots` has carried real per-shot x/y/xG/situation/outcome for every
synced match since 2026-08-29, and until now the only place any of it was
drawn was one match at a time on the match report. League-wide it is the
richest thing this project stores and nothing rendered it. This payload
ships the whole season's shots plus the aggregates a reader needs to make
sense of 1,100 dots.

Coordinates are FotMob's: `x` runs along the pitch length 0-105 toward the
goal being attacked, `y` across the width 0-68. Every shot is already in
"attacking toward x=105" frame regardless of home/away, so the atlas draws
one attacking half and nothing is mirrored here. Values are clamped to the
pitch on the client, never here - an out-of-range value is real data and
is shipped as recorded.

Nothing in this module estimates anything. `xg` is FotMob's per-shot value
as stored; `zone_xg` is the plain mean of those values inside each zone,
with the count alongside so a zone built on three shots reads as three
shots. A player's "goals minus xG" is arithmetic on stored fields.
"""
from fpl_agent.monitoring.dashboard.context import DashboardContext

# 6 columns along the attacking half (x 52.5-105), 4 rows across the width.
_ZONE_COLS = 6
_ZONE_ROWS = 4
_HALF_X = 52.5
_PITCH_X = 105.0
_PITCH_Y = 68.0


def _zone_of(x: float, y: float) -> tuple[int, int] | None:
    if x < _HALF_X:
        return None
    col = min(_ZONE_COLS - 1, int((x - _HALF_X) / ((_PITCH_X - _HALF_X) / _ZONE_COLS)))
    row = min(_ZONE_ROWS - 1, max(0, int(y / (_PITCH_Y / _ZONE_ROWS))))
    return col, row


def build_atlas_payload(ctx: DashboardContext) -> dict:
    from fpl_agent.database.connection import get_connection

    conn = get_connection()
    try:
        mine = set(ctx.squad_ids or ()) if ctx is not None else set()

        rows = conn.execute(
            "SELECT s.player_id, s.player_name, s.team_id, t.short_name AS team_short, t.code AS team_code, "
            "       s.minute, s.x, s.y, s.xg, s.outcome, s.situation, s.shot_type, s.period, "
            "       m.fotmob_match_id, m.home_team_id, m.away_team_id, m.kickoff_utc "
            "FROM match_shots s "
            "JOIN match_intelligence m ON m.id = s.match_id "
            "LEFT JOIN teams t ON t.id = s.team_id "
            "WHERE s.x IS NOT NULL AND s.y IS NOT NULL "
            "ORDER BY m.kickoff_utc, s.minute"
        ).fetchall()

        shots = []
        by_player: dict[int, dict] = {}
        by_team: dict[int, dict] = {}
        zone_sum: dict[tuple[int, int], list[float]] = {}
        situations: dict[str, int] = {}

        for r in rows:
            pid = r["player_id"]
            xg = float(r["xg"]) if r["xg"] is not None else None
            is_goal = r["outcome"] == "Goal"
            shots.append({
                "player_id": pid,
                "player": r["player_name"],
                "team_id": r["team_id"],
                "team": r["team_short"],
                "team_code": r["team_code"],
                "minute": r["minute"],
                "x": round(float(r["x"]), 2),
                "y": round(float(r["y"]), 2),
                "xg": round(xg, 3) if xg is not None else None,
                "outcome": r["outcome"],
                "situation": r["situation"],
                "foot": r["shot_type"],
                "match": r["fotmob_match_id"],
                "mine": pid in mine,
            })
            situations[r["situation"] or "Unknown"] = situations.get(r["situation"] or "Unknown", 0) + 1

            if pid is not None:
                p = by_player.setdefault(pid, {
                    "player_id": pid, "player": r["player_name"], "team": r["team_short"],
                    "team_code": r["team_code"], "shots": 0, "goals": 0, "xg": 0.0,
                    "on_target": 0, "mine": pid in mine,
                })
                p["shots"] += 1
                p["goals"] += 1 if is_goal else 0
                p["xg"] += xg or 0.0
                p["on_target"] += 1 if r["outcome"] in ("Goal", "AttemptSaved") else 0

            if r["team_id"] is not None:
                tm = by_team.setdefault(r["team_id"], {
                    "team_id": r["team_id"], "team": r["team_short"], "team_code": r["team_code"],
                    "shots": 0, "goals": 0, "xg": 0.0,
                })
                tm["shots"] += 1
                tm["goals"] += 1 if is_goal else 0
                tm["xg"] += xg or 0.0

            z = _zone_of(float(r["x"]), float(r["y"]))
            if z is not None and xg is not None:
                zone_sum.setdefault(z, []).append(xg)

        players = sorted(by_player.values(), key=lambda p: p["xg"], reverse=True)
        for p in players:
            p["xg"] = round(p["xg"], 2)
            p["xg_per_shot"] = round(p["xg"] / p["shots"], 3) if p["shots"] else 0.0
            # Positive = scoring more than the chances were worth.
            p["goals_minus_xg"] = round(p["goals"] - p["xg"], 2)
        teams = sorted(by_team.values(), key=lambda t: t["xg"], reverse=True)
        for t in teams:
            t["xg"] = round(t["xg"], 2)
            t["goals_minus_xg"] = round(t["goals"] - t["xg"], 2)

        zones = [
            {
                "col": c, "row": rw,
                "x0": round(_HALF_X + c * (_PITCH_X - _HALF_X) / _ZONE_COLS, 2),
                "x1": round(_HALF_X + (c + 1) * (_PITCH_X - _HALF_X) / _ZONE_COLS, 2),
                "y0": round(rw * _PITCH_Y / _ZONE_ROWS, 2),
                "y1": round((rw + 1) * _PITCH_Y / _ZONE_ROWS, 2),
                "n": len(zone_sum.get((c, rw), [])),
                "mean_xg": round(sum(zone_sum[(c, rw)]) / len(zone_sum[(c, rw)]), 3) if zone_sum.get((c, rw)) else None,
            }
            for c in range(_ZONE_COLS) for rw in range(_ZONE_ROWS)
        ]

        goals = sum(1 for s in shots if s["outcome"] == "Goal")
        total_xg = sum(s["xg"] for s in shots if s["xg"] is not None)
        return {
            "has_shots": bool(shots),
            "pitch": {"length": _PITCH_X, "width": _PITCH_Y, "half_x": _HALF_X},
            "totals": {
                "shots": len(shots),
                "goals": goals,
                "xg": round(total_xg, 1),
                "matches": len({s["match"] for s in shots}),
                "mine_shots": sum(1 for s in shots if s["mine"]),
                "mine_goals": sum(1 for s in shots if s["mine"] and s["outcome"] == "Goal"),
                "mine_xg": round(sum(s["xg"] or 0 for s in shots if s["mine"]), 1),
            },
            "situations": sorted(situations.items(), key=lambda kv: kv[1], reverse=True),
            "shots": shots,
            "players": players[:60],
            "teams": teams,
            "zones": zones,
            "method": (
                "Every shot FotMob recorded in a synced match this season. Dot area is proportional to "
                "FotMob's own xG for that shot; a dot is filled only for a goal. Zone shading is the "
                "plain mean xG of shots inside that zone, with the shot count shown - it is chance "
                "quality by location, not a model. Nothing here is estimated."
            ),
        }
    finally:
        conn.close()
