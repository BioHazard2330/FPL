"""THE GAMEWEEK REPORT - one finished gameweek, read back: what you scored against everyone and against the top ten
thousand, where the rank was won and lost, the armband, the transfers, what the plan of record would have scored, how far
the model was off, and how much of it was luck.

Everything is stored data: your picks and summary (`my_team_picks`, `my_team_gw_summary`), FPL's per-player points and
expected stats (`player_gw_stats`), the top-10k ownership sample of that gameweek (`player_sample_ownership_history`), the
predictions frozen at its deadline (`prediction_outcomes`) and the last week plan made before it
(`decisions`, type `week_plan`).

Stated simplifications: the plan's score is its eleven and armband on the real points with no automatic substitutions
(the vice takes the armband when the captain did not play), and its transfers are free (it never planned a hit that week
unless its moves exceeded the free transfers, in which case the hit is charged); a player's points are his gameweek total
(both matches in a double)."""
import json
import sqlite3

from fpl_agent.models.luck_audit import _scoring_points, player_gw_luck

SWINGS = 6


def _names(conn: sqlite3.Connection) -> dict[int, dict]:
    return {
        r["id"]: {"name": r["web_name"], "team_short": r["short_name"], "team_code": r["code"], "position": r["pos"], "photo_code": r["photo"]}
        for r in conn.execute(
            "SELECT p.id, p.web_name, p.code AS photo, t.short_name, t.code, et.singular_name_short AS pos FROM players p "
            "JOIN teams t ON t.id = p.team_id JOIN element_types et ON et.id = p.element_type"
        )
    }


def plan_of_record(conn: sqlite3.Connection, event: int) -> tuple[dict, str] | None:
    """The last week plan for `event` stored before its deadline."""
    deadline = conn.execute("SELECT deadline_time FROM events WHERE id = ?", (event,)).fetchone()
    if deadline is None:
        return None
    cutoff = deadline["deadline_time"].replace("Z", "+00:00")
    for r in conn.execute(
        "SELECT created_at, detail FROM decisions WHERE decision_type = 'week_plan' AND created_at <= ? ORDER BY created_at DESC LIMIT 60",
        (cutoff,),
    ):
        detail = json.loads(r["detail"])
        if detail.get("event") == event:
            return detail, r["created_at"]
    return None


def _xi_score(starting: list[int], captain: int | None, vice: int | None, pts: dict[int, int], mins: dict[int, int]) -> int:
    total = sum(pts.get(p, 0) for p in starting)
    armband = captain if captain is not None and mins.get(captain, 0) > 0 else vice
    return total + (pts.get(armband, 0) if armband is not None else 0)


_MIN = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}


def automatic_subs(squad: list[dict]) -> list[tuple[int, int]]:
    """FPL's automatic substitutions: each starter who did not play, in squad order, is replaced by the first bench player
    (in bench order) who played and keeps a legal formation; a goalkeeper only for a goalkeeper. Returns (out, in)."""
    xi = [x for x in squad if x["starting"]]
    bench = [x for x in squad if not x["starting"]]
    used: set[int] = set()
    lineup = [x["player_id"] for x in xi]
    pos = {x["player_id"]: x.get("position") for x in squad}
    played = {x["player_id"]: x["minutes"] > 0 for x in squad}
    subs = []
    for out in [x["player_id"] for x in xi if not played[x["player_id"]]]:
        for b in bench:
            pid = b["player_id"]
            if pid in used or not played[pid] or (pos[out] == "GKP") != (pos[pid] == "GKP"):
                continue
            trial = [pid if q == out else q for q in lineup]
            counts = {k: sum(1 for q in trial if pos[q] == k) for k in _MIN}
            if all(counts[k] >= need for k, need in _MIN.items()):
                lineup = trial
                used.add(pid)
                subs.append((out, pid))
                break
    return subs


def autosub_watch(squad: list[dict], minutes: dict[int, int], done: dict[int, bool]) -> list[dict]:
    """During a gameweek: for each starter on 0 minutes, who comes on. `done[player]` says whether his club's matches are
    all over. A starter whose match is over is out and the substitution is made (`made`); one still to play has the bench
    player who would replace him if he does not (`standby`). Uses FPL's rule (`automatic_subs`), treating every bench
    player whose match is not over as available."""
    rows = [{**x, "minutes": minutes.get(x["player_id"], 0)} for x in squad]
    pending = {x["player_id"] for x in rows if x["starting"] and x["minutes"] == 0 and not done.get(x["player_id"], False)}
    out_for_sure = {x["player_id"] for x in rows if x["starting"] and x["minutes"] == 0 and done.get(x["player_id"], False)}
    result = []
    for group, status in ((out_for_sure, "made"), (pending, "standby")):
        if not group:
            continue
        trial = []
        for x in rows:
            played = x["minutes"] > 0 or (not x["starting"] and not done.get(x["player_id"], False))
            if x["starting"] and x["player_id"] in group:
                played = False
            elif x["starting"]:
                played = True
            trial.append({**x, "minutes": 1 if played else 0})
        for out, into in automatic_subs(trial):
            if out in group:
                result.append({"out": out, "into": into, "status": status})
        for pid in group:
            if not any(r["out"] == pid for r in result):
                result.append({"out": pid, "into": None, "status": status})
    return result


def gameweek_review(conn: sqlite3.Connection, entry_id: int, event: int) -> dict | None:
    from fpl_agent.models.captain_autopsy import captain_autopsy
    from fpl_agent.models.rules import current_season

    season = current_season(conn)
    me = conn.execute("SELECT * FROM my_team_gw_summary WHERE entry_id = ? AND event = ?", (entry_id, event)).fetchone()
    picks = conn.execute(
        "SELECT player_id, squad_slot, multiplier, is_captain, is_vice_captain, active_chip FROM my_team_picks "
        "WHERE entry_id = ? AND event = ? ORDER BY squad_slot", (entry_id, event),
    ).fetchall()
    stats = {r["player_id"]: dict(r) for r in conn.execute("SELECT * FROM player_gw_stats WHERE season = ? AND event = ?", (season, event))}
    if me is None or not picks or not stats:
        return None
    names = _names(conn)
    pts = {pid: s["total_points"] for pid, s in stats.items()}
    mins = {pid: s["minutes"] for pid, s in stats.items()}
    prev = conn.execute("SELECT overall_rank, total_points FROM my_team_gw_summary WHERE entry_id = ? AND event = ?", (entry_id, event - 1)).fetchone()
    ev = conn.execute("SELECT average_entry_score, highest_score FROM events WHERE id = ?", (event,)).fetchone()
    hits = me["event_transfers_cost"] or 0
    scored = me["points"] - hits

    scoring = _scoring_points(conn, season)
    predicted = {r["player_id"]: r["predicted_median"] for r in conn.execute(
        "SELECT player_id, predicted_median FROM prediction_outcomes WHERE season = ? AND event = ? AND predicted_median IS NOT NULL", (season, event))}
    squad = []
    for p in picks:
        s = stats.get(p["player_id"])
        info = names.get(p["player_id"], {})
        deserved = None
        if s is not None and info.get("position") in scoring:
            luck = player_gw_luck(s, *scoring[info["position"]])
            deserved = round(s["total_points"] - luck.total, 1)
        squad.append({
            "player_id": p["player_id"], **info, "slot": p["squad_slot"], "starting": p["squad_slot"] <= 11,
            "multiplier": p["multiplier"], "captain": bool(p["is_captain"]), "vice": bool(p["is_vice_captain"]),
            "points": s["total_points"] if s else 0, "minutes": s["minutes"] if s else 0,
            "xg": s["xg"] if s else None, "xa": s["xa"] if s else None, "bonus": s["bonus"] if s else 0,
            "predicted": round(predicted[p["player_id"]], 1) if p["player_id"] in predicted else None, "deserved": deserved,
        })
    chip = next((p["active_chip"] for p in picks if p["active_chip"]), None)
    subs = automatic_subs(squad) if chip != "bboost" else []
    for out, into in subs:
        a_out = next(x for x in squad if x["player_id"] == out)
        a_in = next(x for x in squad if x["player_id"] == into)
        a_in["multiplier"], a_out["multiplier"] = max(a_out["multiplier"], 1) if not a_out["captain"] else 1, 0
        a_in["subbed_on"], a_out["subbed_off"] = True, True
    counted = [x for x in squad if x["multiplier"] > 0]
    deserved_total = sum((x["deserved"] if x["deserved"] is not None else x["points"]) * x["multiplier"] for x in counted)
    predicted_total = sum((x["predicted"] or 0) * x["multiplier"] for x in counted if x["predicted"] is not None)

    # against the top ten thousand: each player's (your multiplier - their effective ownership) x his points
    sample = {r["player_id"]: r["eo"] for r in conn.execute(
        "SELECT player_id, sum_multiplier * 1.0 / sample_size AS eo FROM player_sample_ownership_history WHERE season = ? AND event = ?",
        (season, event))}
    field = None
    swings = []
    if sample:
        field = round(sum(eo * pts.get(pid, 0) for pid, eo in sample.items()), 1)
        mult = {x["player_id"]: x["multiplier"] for x in squad}
        for pid in set(sample) | set(mult):
            swing = (mult.get(pid, 0) - sample.get(pid, 0.0)) * pts.get(pid, 0)
            if abs(swing) >= 0.5:
                swings.append({"player_id": pid, **names.get(pid, {}), "points": pts.get(pid, 0), "yours": mult.get(pid, 0),
                               "field_eo": round(sample.get(pid, 0.0), 2), "swing": round(swing, 1)})
        swings.sort(key=lambda s: -s["swing"])
    gains = [s for s in swings if s["swing"] > 0][:SWINGS]
    losses = sorted([s for s in swings if s["swing"] < 0], key=lambda s: s["swing"])[:SWINGS]

    transfers = []
    for t in conn.execute("SELECT element_in, element_out, element_in_cost, element_out_cost FROM my_team_transfers WHERE entry_id = ? AND event = ?",
                          (entry_id, event)):
        transfers.append({
            "into": {"player_id": t["element_in"], **names.get(t["element_in"], {}), "points": pts.get(t["element_in"], 0),
                     "price": (t["element_in_cost"] or 0) / 10},
            "out": {"player_id": t["element_out"], **names.get(t["element_out"], {}), "points": pts.get(t["element_out"], 0),
                    "price": (t["element_out_cost"] or 0) / 10},
        })

    plan = None
    stored = plan_of_record(conn, event)
    if stored is not None:
        detail, made_at = stored
        after = detail["lineup_after"]
        starting = [p["player_id"] for p in after["starting"]]
        plan_hits = max(0, len(detail.get("moves", [])) - (detail.get("free_transfers") or 0)) * 4
        plan_score = _xi_score(starting, after.get("captain_id"), after.get("vice_id"), pts, mins) - plan_hits
        plan = {
            "made_at": made_at, "score": plan_score, "hits": plan_hits,
            "captain": {"player_id": after.get("captain_id"), **names.get(after.get("captain_id"), {}), "points": pts.get(after.get("captain_id"), 0)},
            "moves": [
                {"out": {"player_id": m["out"]["player_id"], **names.get(m["out"]["player_id"], {}), "points": pts.get(m["out"]["player_id"], 0)},
                 "into": {"player_id": m["into"]["player_id"], **names.get(m["into"]["player_id"], {}), "points": pts.get(m["into"]["player_id"], 0)}}
                for m in detail.get("moves", [])
            ],
            "followed": sorted(starting) == sorted(x["player_id"] for x in squad if x["starting"]),
        }

    autopsy = next((a for a in captain_autopsy(conn, entry_id) if a["event"] == event), None)
    top = sorted(((pid, p) for pid, p in pts.items()), key=lambda kv: -kv[1])[:5]
    return {
        "event": event, "chip": chip, "points": scored, "raw_points": me["points"], "hits": hits,
        "average": ev["average_entry_score"] if ev else None, "highest": ev["highest_score"] if ev else None,
        "top10k_field": field, "total": me["total_points"], "rank": me["overall_rank"],
        "previous_rank": prev["overall_rank"] if prev else None, "bench_points": me["points_on_bench"],
        "squad": squad, "predicted": round(predicted_total, 1), "deserved": round(deserved_total, 1),
        "counted": sum(x["points"] * x["multiplier"] for x in counted),
        "subs": [{"out": names.get(o, {}).get("name"), "into": names.get(i, {}).get("name")} for o, i in subs],
        "gains": gains, "losses": losses, "transfers": transfers, "plan": plan, "captain": autopsy,
        "stars": [{"player_id": pid, **names.get(pid, {}), "points": p} for pid, p in top],
        "history": [dict(r) for r in conn.execute(
            "SELECT s.event, s.points, s.overall_rank AS rank, e.average_entry_score AS average FROM my_team_gw_summary s "
            "LEFT JOIN events e ON e.id = s.event WHERE s.entry_id = ? ORDER BY s.event", (entry_id,))],
        "events": [r["event"] for r in conn.execute(
            "SELECT DISTINCT event FROM my_team_gw_summary WHERE entry_id = ? AND event IN "
            "(SELECT DISTINCT event FROM player_gw_stats WHERE season = ?) ORDER BY event", (entry_id, season))],
    }
