"""THE ROLE ENGINE: what each player actually does and where, from every finished league match's full FotMob record
(`ingestion/match_detail.py`).

- Roles: the slot he lined up in each start (GK, CB, FB, WB, DM, CM, AM, W, ST, with a side for the wide ones), his usual
  role, and a change when his last two starts were both in a role he had not held in his earlier starts.
- Profile per 90: chances created, xA, passes into the final third, line-breaking passes, dribbles, box touches,
  recoveries, defensive actions, CBIT (clearances, blocks, interceptions, tackles) and how often he reaches FPL's
  defensive-contribution threshold (10 CBIT for a defender, 12 CBIT + recoveries otherwise).
- Depth chart: each club's latest eleven on the grid, with who else has started in each slot this season.
- Set pieces: corners taken (FotMob's count per player), penalties and direct free kicks shot (the stored shots), for
  the season and the last three matches; a new corner taker when the last three's leader is not the season's.
- What changed: role moves, players breaking into the eleven or dropping out of it, new corner takers, league-wide."""
import json
import sqlite3
from collections import Counter, defaultdict

from fpl_agent.ingestion.match_detail import stats_for

PROFILE = {
    "chances_created": "Chances created", "expected_assists": "xA", "passes_into_final_third": "Final-third passes",
    "line_breaking_passes": "Line-breaking passes", "dribbles_succeeded": "Dribbles", "touches_opp_box": "Box touches",
    "recoveries": "Recoveries", "defensive_actions": "Defensive actions", "accurate_crosses": "Crosses",
}


def _slot(role: str | None, y: float | None) -> str | None:
    if role is None:
        return None
    if role in ("FB", "WB", "W") and y is not None:
        return f"{role}-{'R' if y > 0.5 else 'L'}"
    return role


def _cbit(s: dict) -> float:
    return sum(float(s.get(k) or 0) for k in ("clearances", "shot_blocks", "interceptions", "matchstats.headers.tackles"))


def _positions(conn: sqlite3.Connection) -> dict[int, str]:
    return {r[0]: r[1] for r in conn.execute("SELECT p.id, et.singular_name_short FROM players p JOIN element_types et ON et.id = p.element_type")}


def player_roles(conn: sqlite3.Connection, player_ids: list[int]) -> dict[int, dict]:
    pos = _positions(conn)
    by: dict[int, list[dict]] = defaultdict(list)
    for r in stats_for(conn, player_ids=player_ids):
        by[r["player_id"]].append(r)
    out = {}
    for pid, rows in by.items():
        starts = [r for r in rows if r["started"] and r["role"]]
        mins = sum(float(r["stats"].get("minutes_played") or 0) for r in rows)
        roles = Counter(_slot(r["role"], r["y"]) for r in starts)
        usual = roles.most_common(1)[0][0] if roles else None
        change = None
        if len(starts) >= 5:
            last = [_slot(r["role"], r["y"]) for r in starts[-2:]]
            earlier = Counter(_slot(r["role"], r["y"]) for r in starts[:-2])
            if last[0] == last[1] and earlier.get(last[0], 0) == 0:
                change = {"from": earlier.most_common(1)[0][0], "to": last[0]}
        per90 = {}
        if mins >= 90:
            for k in PROFILE:
                per90[k] = round(sum(float(r["stats"].get(k) or 0) for r in rows) * 90 / mins, 2)
            per90["cbit"] = round(sum(_cbit(r["stats"]) for r in rows) * 90 / mins, 2)
        threshold, extra = (10, False) if pos.get(pid) == "DEF" else (12, True)
        played = [r for r in rows if float(r["stats"].get("minutes_played") or 0) >= 60]
        hits = sum(1 for r in played if _cbit(r["stats"]) + (float(r["stats"].get("recoveries") or 0) if extra else 0) >= threshold)
        out[pid] = {
            "player_id": pid, "usual": usual, "roles": dict(roles), "last": [_slot(r["role"], r["y"]) for r in starts[-3:]], "change": change,
            "per90": per90, "defcon": {"hits": hits, "matches": len(played)} if pos.get(pid) != "GKP" else None,
            "corners": int(sum(float(r["stats"].get("corners") or 0) for r in rows)), "minutes": int(mins),
        }
    return out


def _names(conn: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    return {r["id"]: r for r in conn.execute(
        "SELECT p.id, p.web_name, p.status, p.chance_of_playing_next_round AS chance, p.team_id, et.singular_name_short AS pos "
        "FROM players p JOIN element_types et ON et.id = p.element_type")} if _has_chance(conn) else {r["id"]: r for r in conn.execute(
        "SELECT p.id, p.web_name, p.status, NULL AS chance, p.team_id, et.singular_name_short AS pos FROM players p JOIN element_types et ON et.id = p.element_type")}


def _has_chance(conn: sqlite3.Connection) -> bool:
    return any(r[1] == "chance_of_playing_next_round" for r in conn.execute("PRAGMA table_info(players)"))


def _matches(rows: list[dict]) -> list[int]:
    seen = []
    for r in rows:
        if r["match_id"] not in seen:
            seen.append(r["match_id"])
    return seen


def depth_chart(conn: sqlite3.Connection, team_id: int) -> dict | None:
    rows = stats_for(conn, team_id=team_id)
    if not rows:
        return None
    names = _names(conn)
    feed = {r[0]: r[1] for r in conn.execute(
        "SELECT h.player_id, h.start_percent FROM player_start_probability_history h JOIN players p ON p.id = h.player_id "
        "WHERE p.team_id = ? AND h.fetched_at = (SELECT MAX(fetched_at) FROM player_start_probability_history h2 WHERE h2.player_id = h.player_id)", (team_id,))}
    order = _matches(rows)
    latest = order[-1]
    by_slot: dict[str, Counter] = defaultdict(Counter)
    recent: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r["started"] and r["role"]:
            slot = _slot(r["role"], r["y"])
            by_slot[slot][r["player_id"]] += 1
            if r["match_id"] in order[-6:]:
                recent[slot][r["player_id"]] += 1

    def person(pid: int, slot: str) -> dict:
        n = names.get(pid)
        return {"player_id": pid, "name": n["web_name"] if n else str(pid), "status": n["status"] if n else None,
                "chance": n["chance"] if n else None, "start_percent": feed.get(pid), "starts_here": by_slot[slot][pid], "recent_here": recent[slot][pid]}

    eleven = []
    for r in sorted((r for r in rows if r["match_id"] == latest and r["started"]), key=lambda r: (r["x"] or 0, r["y"] or 0)):
        slot = _slot(r["role"], r["y"])
        cover = [person(p, slot) for p, _ in by_slot[slot].most_common() if p != r["player_id"]][:3]
        eleven.append({"x": r["x"], "y": r["y"], "role": r["role"], "slot": slot, "starter": person(r["player_id"], slot), "cover": cover})
    return {"team_id": team_id, "formation": next((r["formation"] for r in rows if r["match_id"] == latest and r["formation"]), None),
            "match_id": latest, "matches": len(order), "eleven": eleven}


def set_pieces(conn: sqlite3.Connection, team_id: int) -> dict:
    rows = stats_for(conn, team_id=team_id)
    order = _matches(rows)
    names = _names(conn)
    season, last3 = Counter(), Counter()
    for r in rows:
        c = float(r["stats"].get("corners") or 0)
        if c:
            season[r["player_id"]] += c
            if r["match_id"] in order[-3:]:
                last3[r["player_id"]] += c
    pens, fks = Counter(), Counter()
    for (story,) in conn.execute(
        "SELECT ms.story_json FROM match_story ms JOIN match_intelligence mi ON mi.id = ms.match_id WHERE mi.home_team_id = ? OR mi.away_team_id = ?", (team_id, team_id)):
        for s in json.loads(story).get("shots") or []:
            pid = s.get("pid")
            if pid in names and names[pid]["team_id"] == team_id:
                if s.get("sit") == "Penalty":
                    pens[pid] += 1
                elif s.get("sit") == "FreeKick":
                    fks[pid] += 1
    fmt = lambda c: [{"player_id": p, "name": names[p]["web_name"] if p in names else str(p), "count": int(n)} for p, n in c.most_common(3)]
    new_taker = None
    if season and last3:
        lead_season, lead_recent = season.most_common(1)[0][0], last3.most_common(1)[0][0]
        if lead_season != lead_recent and last3[lead_recent] >= 3:
            new_taker = {"player_id": lead_recent, "name": names[lead_recent]["web_name"] if lead_recent in names else None,
                         "recent": int(last3[lead_recent]), "previous": names[lead_season]["web_name"] if lead_season in names else None}
    return {"corners": fmt(season), "corners_last3": fmt(last3), "penalties": fmt(pens), "free_kicks": fmt(fks), "new_corner_taker": new_taker}


def league_changes(conn: sqlite3.Connection) -> list[dict]:
    names = _names(conn)
    teams = {r[0]: r[1] for r in conn.execute("SELECT id, short_name FROM teams")}
    out = []
    by_team: dict[int, list[dict]] = defaultdict(list)
    for r in stats_for(conn):
        by_team[r["team_id"]].append(r)
    for tid, rows in by_team.items():
        order = _matches(rows)
        if len(order) < 5:
            continue
        last2, prior = set(order[-2:]), order[-7:-2]
        starts: dict[int, list[int]] = defaultdict(list)
        for r in rows:
            if r["started"]:
                starts[r["player_id"]].append(r["match_id"])
        for pid, ms in starts.items():
            n = names.get(pid)
            if n is None:
                continue
            in_last = sum(1 for m in ms if m in last2)
            in_prior = sum(1 for m in ms if m in prior)
            if in_last == 2 and in_prior <= 1 and len(prior) >= 4:
                out.append({"kind": "into_eleven", "player_id": pid, "name": n["web_name"], "team": teams.get(tid),
                            "text": f"started the last 2 after {in_prior} of the {len(prior)} before"})
            if in_last == 0 and in_prior >= 4 and n["status"] == "a":
                out.append({"kind": "out_of_eleven", "player_id": pid, "name": n["web_name"], "team": teams.get(tid),
                            "text": f"started {in_prior} of {len(prior)}, then none of the last 2, and is fit"})
        sp = set_pieces(conn, tid)
        if sp["new_corner_taker"]:
            t = sp["new_corner_taker"]
            out.append({"kind": "corner_taker", "player_id": t["player_id"], "name": t["name"], "team": teams.get(tid),
                        "text": f"took {t['recent']} corners in the last 3 matches; {t['previous']} led the season"})
    ids = [pid for pid, n in names.items()]
    for pid, r in player_roles(conn, ids).items():
        if r["change"] and pid in names:
            out.append({"kind": "role", "player_id": pid, "name": names[pid]["web_name"], "team": teams.get(names[pid]["team_id"]),
                        "text": f"moved from {r['change']['from']} to {r['change']['to']} for his last 2 starts"})
    order = {"role": 0, "corner_taker": 1, "into_eleven": 2, "out_of_eleven": 3}
    return sorted(out, key=lambda c: (order[c["kind"]], c["team"] or ""))


ADVANCED = {"DEF": {"W", "AM", "CM", "ST"}, "MID": {"ST"}}


def out_of_position(conn: sqlite3.Connection, min_starts: int = 3) -> list[dict]:
    """Players FPL lists deeper than they play: a defender lined up as a winger, midfielder or forward, a midfielder as the
    striker. FPL scores him by its own position, so he gets the defender's clean sheet with an attacker's chances."""
    names = _names(conn)
    teams = {r[0]: r[1] for r in conn.execute("SELECT id, short_name FROM teams")}
    price = {r[0]: r[1] for r in conn.execute("SELECT player_id, value_tenths FROM player_price_history WHERE valid_until IS NULL")}
    starts: dict[int, Counter] = defaultdict(Counter)
    last: dict[int, list[str]] = defaultdict(list)
    for r in stats_for(conn):
        if r["started"] and r["role"]:
            slot = _slot(r["role"], r["y"])
            starts[r["player_id"]][slot] += 1
            last[r["player_id"]].append(slot)
    out = []
    for pid, c in starts.items():
        n = names.get(pid)
        if n is None or n["pos"] not in ADVANCED:
            continue
        total = sum(c.values())
        ahead = sum(v for k, v in c.items() if k.split("-")[0] in ADVANCED[n["pos"]])
        if total < min_starts or ahead / total < 0.5:
            continue
        usual = max((k for k in c if k.split("-")[0] in ADVANCED[n["pos"]]), key=c.get)
        out.append({"player_id": pid, "name": n["web_name"], "team": teams.get(n["team_id"]), "fpl_position": n["pos"], "plays_as": usual,
                    "share": f"{ahead} of {total} starts", "recent": last[pid][-3:], "price_tenths": price.get(pid)})
    roles = player_roles(conn, [o["player_id"] for o in out])
    for o in out:
        p = roles.get(o["player_id"], {}).get("per90", {})
        o["per90"] = {k: p.get(k) for k in ("chances_created", "expected_assists", "touches_opp_box", "cbit")}
    return sorted(out, key=lambda o: -(o["per90"].get("touches_opp_box") or 0))
