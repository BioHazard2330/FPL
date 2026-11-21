"""THE MANAGER BRAIN: how each manager uses his squad, from every substitution in the season's match stories, the line-ups
and the midweek cup and European ties.

- Changes by score: when he makes his first change while ahead, level and behind; what kind (like for like, chasing,
  protecting a lead, managing minutes, tactical, at half-time, injury).
- First off: who he takes off first, and how often, with the usual minute; who he brings on for whom (the pairs that
  repeat) and his impact substitutes (league goals and assists off the bench).
- Midweek rotation: changes to the eleven in a league match within four days after a cup or European tie, against
  changes otherwise; per player, league starts after midweek football against starts otherwise.
- Cover: when a regular (started 60%+ of the club's matches) was not in the eleven, who started in his slot instead."""
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import median

from fpl_agent.ingestion.match_detail import stats_for

STATE = lambda margin: "ahead" if margin > 0 else "behind" if margin < 0 else "level"


def _iso(t: str) -> datetime:
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


def manager_brain(conn: sqlite3.Connection, team_id: int) -> dict:
    names = {r[0]: r[1] for r in conn.execute("SELECT id, web_name FROM players")}
    matches = conn.execute(
        "SELECT mi.id, mi.kickoff_utc, mi.home_team_id, mi.away_team_id, ms.story_json FROM match_intelligence mi JOIN match_story ms ON ms.match_id = mi.id "
        "WHERE mi.status = 'FULL_TIME' AND mi.competition LIKE '%Premier%' AND (mi.home_team_id = ? OR mi.away_team_id = ?) ORDER BY mi.kickoff_utc",
        (team_id, team_id),
    ).fetchall()
    first_by_state: dict[str, list[int]] = defaultdict(list)
    kinds: Counter = Counter()
    first_off: Counter = Counter()
    off_minutes: dict[int, list[int]] = defaultdict(list)
    pairs: Counter = Counter()
    for m in matches:
        subs = sorted((s for s in json.loads(m["story_json"]).get("subs") or [] if s.get("team_id") == team_id), key=lambda s: s["minute"])
        if not subs:
            continue
        first = subs[0]
        first_by_state[STATE(first.get("margin") or 0)].append(first["minute"])
        first_off[first.get("off_id")] += 1
        for s in subs:
            kinds[s.get("kind")] += 1
            if s.get("off_id"):
                off_minutes[s["off_id"]].append(s["minute"])
            if s.get("off_id") and s.get("on_id"):
                pairs[(s["off_id"], s["on_id"])] += 1
    n = len(matches)
    impact = [
        {"player_id": r[0], "name": names.get(r[0]), "apps": r[1], "goals": r[2] or 0, "assists": r[3] or 0, "minutes": r[4] or 0}
        for r in conn.execute(
            "SELECT s.player_id, COUNT(*), SUM(s.goals), SUM(s.assists), SUM(s.minutes) FROM player_match_state s JOIN match_intelligence mi ON mi.id = s.match_id "
            "WHERE s.team_id = ? AND s.started = 0 AND s.substituted_on_minute IS NOT NULL AND mi.status = 'FULL_TIME' AND mi.competition LIKE '%Premier%' "
            "GROUP BY s.player_id HAVING COUNT(*) >= 2 ORDER BY SUM(s.goals) + SUM(s.assists) DESC, COUNT(*) DESC LIMIT 4", (team_id,))
    ]
    return {
        "team_id": team_id, "matches": n,
        "first_change": {k: {"median": median(v), "matches": len(v)} for k, v in first_by_state.items()},
        "kinds": dict(kinds.most_common()),
        "first_off": [{"player_id": p, "name": names.get(p), "times": c, "usual_minute": round(median(off_minutes[p]))} for p, c in first_off.most_common(3) if p],
        "pairs": [{"off": names.get(o), "on": names.get(i), "times": c} for (o, i), c in pairs.most_common(4) if c >= 2],
        "impact_subs": impact,
        "midweek": _midweek(conn, team_id, names),
        "cover": _cover(conn, team_id, names),
    }


def _midweek(conn: sqlite3.Connection, team_id: int, names: dict[int, str]) -> dict | None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'cup_match'").fetchone():
        return None
    cups = [_iso(r[0]) for r in conn.execute(
        "SELECT kickoff_utc FROM cup_match WHERE team_id = ? AND status IN ('FULL_TIME', 'FINISHED', 'FT') OR (team_id = ? AND home_score IS NOT NULL)", (team_id, team_id))]
    league = conn.execute(
        "SELECT mi.id, mi.kickoff_utc FROM match_intelligence mi WHERE mi.status = 'FULL_TIME' AND mi.competition LIKE '%Premier%' "
        "AND (mi.home_team_id = ? OR mi.away_team_id = ?) ORDER BY mi.kickoff_utc", (team_id, team_id)).fetchall()
    xi = defaultdict(set)
    for r in conn.execute(f"SELECT match_id, player_id FROM player_match_state WHERE team_id = ? AND started = 1", (team_id,)):
        xi[r[0]].add(r[1])
    after, normal = [], []
    starts_after: Counter = Counter()
    starts_normal: Counter = Counter()
    for prev, cur in zip(league, league[1:]):
        k = _iso(cur["kickoff_utc"])
        changes = len(xi[cur["id"]] - xi[prev["id"]]) if xi[cur["id"]] and xi[prev["id"]] else None
        midweek = any(timedelta(0) < k - c <= timedelta(days=4) for c in cups)
        if changes is not None:
            (after if midweek else normal).append(changes)
        for p in xi[cur["id"]]:
            (starts_after if midweek else starts_normal)[p] += 1
    if not after:
        return {"after_cup": None, "otherwise": round(sum(normal) / len(normal), 1) if normal else None, "rested": []}
    rested = []
    for p, s in starts_normal.items():
        share_n = s / max(len(normal), 1)
        share_a = starts_after[p] / len(after)
        if share_n >= 0.7 and share_a <= share_n - 0.34:
            rested.append({"player_id": p, "name": names.get(p), "after_cup": f"{starts_after[p]} of {len(after)}", "otherwise": f"{s} of {len(normal)}"})
    return {"after_cup": round(sum(after) / len(after), 1), "after_matches": len(after), "otherwise": round(sum(normal) / len(normal), 1) if normal else None, "rested": rested}


def _cover(conn: sqlite3.Connection, team_id: int, names: dict[int, str]) -> list[dict]:
    from fpl_agent.models.roles import _slot

    rows = stats_for(conn, team_id=team_id)
    matches = sorted({r["match_id"] for r in rows})
    if not matches:
        return []
    slot_of: dict[int, Counter] = defaultdict(Counter)
    starters: dict[int, dict[int, str]] = defaultdict(dict)
    for r in rows:
        if r["started"] and r["role"]:
            s = _slot(r["role"], r["y"])
            slot_of[r["player_id"]][s] += 1
            starters[r["match_id"]][r["player_id"]] = s
    out = []
    for pid, c in slot_of.items():
        total = sum(c.values())
        if total < 0.6 * len(matches):
            continue
        slot = c.most_common(1)[0][0]
        missed = [m for m in matches if pid not in starters[m]]
        if not missed:
            continue
        played = [m for m in matches if pid in starters[m]]
        partners = {p for p in slot_of if sum(1 for m in played if starters[m].get(p) == slot) >= 0.5 * len(played)}
        stand_ins = Counter(p for m in missed for p, s in starters[m].items() if s == slot and p != pid and p not in partners)
        if stand_ins:
            out.append({"player_id": pid, "name": names.get(pid), "slot": slot, "missed": len(missed),
                        "stand_ins": [{"name": names.get(p), "player_id": p, "times": t} for p, t in stand_ins.most_common(2)]})
    return sorted(out, key=lambda o: -o["missed"])
