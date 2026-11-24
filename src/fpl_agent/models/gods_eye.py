"""GOD'S EYE ON ONE PLAYER: everything the role engine, the manager brain and the full match records know about him, on
his page.

- Role strip: his last ten league starts (opponent, slot, minutes, FotMob rating, goals and assists).
- Profile: per-90 measures against every player who usually plays his role (270+ minutes), as percentiles.
- Duties: corners (and his share of the club's), penalties and direct free kicks shot.
- His manager: how often he goes off first, his usual minute off, who covers him and whom he covers.
- Match reads: each of his last five matches read against his own per-90 numbers - what he did that was well above or
  below his usual (1.6 times or more, or under half), his returns, and his role when it was not his usual one."""
import sqlite3
from collections import defaultdict

from fpl_agent.ingestion.match_detail import stats_for
from fpl_agent.models import roles

ROLE_NAME = {"GK": "goalkeeper", "CB": "centre-back", "FB": "full-back", "WB": "wing-back", "DM": "holding midfield", "CM": "central midfield",
             "AM": "number 10", "W": "winger", "ST": "striker"}
READ = {"chances_created": "chances created", "touches_opp_box": "box touches", "passes_into_final_third": "final-third passes",
        "line_breaking_passes": "line-breaking passes", "dribbles_succeeded": "dribbles", "recoveries": "recoveries",
        "total_shots": "shots", "accurate_crosses": "crosses"}
MIN_MINUTES = 270


def _role_name(slot: str | None) -> str:
    if not slot:
        return "-"
    base, _, side = slot.partition("-")
    return f"{'left' if side == 'L' else 'right'} {ROLE_NAME[base]}" if side else ROLE_NAME.get(base, base)


def _percentiles(conn: sqlite3.Connection, pid: int, usual: str | None) -> dict:
    if not usual:
        return {}
    base = usual.split("-")[0]
    totals: dict[int, dict] = defaultdict(lambda: defaultdict(float))
    slots: dict[int, dict] = defaultdict(lambda: defaultdict(int))
    for r in stats_for(conn):
        t = totals[r["player_id"]]
        s = r["stats"]
        t["minutes"] += float(s.get("minutes_played") or 0)
        for k in list(roles.PROFILE) + ["total_shots"]:
            t[k] += float(s.get(k) or 0)
        t["cbit"] += roles._cbit(s)
        if r["started"] and r["role"]:
            slots[r["player_id"]][r["role"]] += 1
    peers = [p for p, c in slots.items() if c and max(c, key=c.get) == base and totals[p]["minutes"] >= MIN_MINUTES]
    if pid not in peers:
        peers.append(pid)
    out = {}
    for k in list(roles.PROFILE) + ["cbit", "total_shots"]:
        rates = {p: totals[p][k] * 90 / totals[p]["minutes"] for p in peers if totals[p]["minutes"]}
        if pid not in rates or len(rates) < 5:
            continue
        mine = rates[pid]
        below = sum(1 for v in rates.values() if v < mine)
        out[k] = {"per90": round(mine, 2), "pct": round(100 * below / (len(rates) - 1)), "peers": len(rates)}
    return out


def player_eye(conn: sqlite3.Connection, pid: int) -> dict | None:
    rows = stats_for(conn, player_ids=[pid])
    if not rows:
        return None
    me = conn.execute("SELECT team_id, web_name FROM players WHERE id = ?", (pid,)).fetchone()
    team_id = me["team_id"]
    teams = {r[0]: r[1] for r in conn.execute("SELECT id, short_name FROM teams")}
    opp = {r[0]: (r[2] if r[1] == team_id else r[1]) for r in conn.execute("SELECT id, home_team_id, away_team_id FROM match_intelligence")}
    role = roles.player_roles(conn, [pid]).get(pid, {})
    mins = sum(float(r["stats"].get("minutes_played") or 0) for r in rows)
    usual90 = {k: sum(float(r["stats"].get(k) or 0) for r in rows) * 90 / mins for k in READ} if mins else {}

    strip = []
    # Every league match he was in the squad for, not only his starts: a strip of starts read "started his last five" for
    # a player benched the match before (McGinn, 2026-11-24).
    for r in rows[-10:]:
        s = r["stats"]
        strip.append({"match_id": r["match_id"], "opponent": teams.get(opp.get(r["match_id"])), "started": bool(r["started"]),
                      "slot": roles._slot(r["role"], r["y"]) if r["started"] else None,
                      "minutes": s.get("minutes_played"), "rating": s.get("rating_title"), "goals": s.get("goals", 0), "assists": s.get("assists", 0)})

    reads = []
    for r in rows[-5:]:
        s = r["stats"]
        m = float(s.get("minutes_played") or 0)
        if m < 10:
            continue
        slot = roles._slot(r["role"], r["y"])
        notes = []
        for k, label in READ.items():
            exp = usual90.get(k, 0) * m / 90
            v = float(s.get(k) or 0)
            if exp >= 1 and v >= 1.6 * exp and v - exp >= 2:
                notes.append((v / exp, f"{v:g} {label} (usually {exp:.1f} in that time)"))
            elif exp >= 2.5 and v <= 0.5 * exp:
                notes.append((exp / max(v, 0.5), f"only {v:g} {label} (usually {exp:.1f})"))
        notes.sort(reverse=True)
        returns = [f"{int(s['goals'])} goal{'s' if s['goals'] > 1 else ''}" for _ in [0] if s.get("goals")] + \
                  [f"{int(s['assists'])} assist{'s' if s['assists'] > 1 else ''}" for _ in [0] if s.get("assists")]
        where = f"{'started' if r['started'] else 'off the bench'}, {int(m)}'"
        if r["started"] and slot and slot != role.get("usual"):
            where += f", played {_role_name(slot)} (usually {_role_name(role.get('usual'))})"
        text = "; ".join([*returns, *[n for _, n in notes[:3]]]) or "nothing well above or below his usual"
        reads.append({"match_id": r["match_id"], "opponent": teams.get(opp.get(r["match_id"])), "kickoff": r["kickoff"], "where": where,
                      "rating": s.get("rating_title"), "read": text})

    sp = roles.set_pieces(conn, team_id)
    club_corners = sum(t["count"] for t in sp["corners"]) or 0
    duties = {
        "corners": role.get("corners", 0), "corner_share": round(role.get("corners", 0) / club_corners, 2) if club_corners else None,
        "penalties": next((t["count"] for t in sp["penalties"] if t["player_id"] == pid), 0),
        "free_kicks": next((t["count"] for t in sp["free_kicks"] if t["player_id"] == pid), 0),
    }

    from fpl_agent.models.dugout import player_usage
    from fpl_agent.models.manager_brain import manager_brain

    brain = manager_brain(conn, team_id)
    usage = next(iter(player_usage(conn, player_ids=[pid])), None)
    depth = roles.depth_chart(conn, team_id) or {"eleven": []}
    my_slot = next((s for s in depth["eleven"] if s["starter"]["player_id"] == pid), None)
    covered_by = my_slot["cover"] if my_slot else next((c["stand_ins"] for c in brain["cover"] if c["player_id"] == pid), [])
    covers_for = [c["name"] for c in brain["cover"] if any(s["player_id"] == pid for s in c["stand_ins"])]
    first_off = next((x for x in brain["first_off"] if x["player_id"] == pid), None)
    return {
        "player_id": pid, "usual_role": _role_name(role.get("usual")), "usual_slot": role.get("usual"), "role_change": role.get("change"),
        "strip": strip, "profile": _percentiles(conn, pid, role.get("usual")), "defcon": role.get("defcon"), "duties": duties,
        "manager": {
            "first_off": first_off, "typical_off": usage["typical_off"] if usage else None, "security": usage["security"] if usage else None,
            "starts": f"{usage['starts']} of {usage['club_matches']}" if usage else None,
            "covered_by": [{"name": c["name"], "player_id": c["player_id"]} for c in covered_by][:3], "covers_for": covers_for,
        },
        "reads": list(reversed(reads)),
    }
