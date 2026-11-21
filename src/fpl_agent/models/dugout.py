"""THE DUGOUT: every club and its manager read from the season's stored matches - how they set up, how they play with and
without the ball, what they do with a lead and when behind, when the manager makes his changes, how much he rotates, and
how secure each player's minutes are under him.

Sources: `team_match_state` (FotMob team stats per match and its opponent's row for the against side), `match_story`
(`state_profile`: chances for and against by game state; `subs`: every substitution with its minute and kind),
`player_match_state` (who started, minute off), `match_coach` (the manager on the sheet). All Premier League matches
at full time this season. Each measure is set against the league as a percentile; style labels are rules over those
percentiles. Game-state rates need 90+ minutes in that state; under that they are shown as missing.

Display and the pundit's evidence only. Measured before (2026-10-16) and refused as a projection input: a club's
rotation index adds nothing to a player's own minutes record. Hook timing per player is already in his own minutes
buckets; the team figure is context."""
import json
import sqlite3
from statistics import median

MIN_STATE_MINUTES = 90


def _pct_rank(values: dict[int, float | None]) -> dict[int, float | None]:
    present = sorted(v for v in values.values() if v is not None)
    out = {}
    for k, v in values.items():
        if v is None or len(present) < 2:
            out[k] = None
            continue
        below = sum(1 for x in present if x < v)
        equal = sum(1 for x in present if x == v)
        out[k] = round(100 * (below + 0.5 * (equal - 1)) / (len(present) - 1))
    return out


def _matches(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, kickoff_utc, home_team_id, away_team_id, home_score, away_score FROM match_intelligence "
        "WHERE status = 'FULL_TIME' AND competition LIKE '%Premier%' ORDER BY kickoff_utc"
    ).fetchall()


def club_profiles(conn: sqlite3.Connection) -> dict[int, dict]:
    teams = {r["id"]: r for r in conn.execute("SELECT id, name, short_name, code FROM teams")}
    matches = _matches(conn)
    ids = [m["id"] for m in matches]
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    tms: dict[tuple[int, int], sqlite3.Row] = {(r["match_id"], r["team_id"]): r for r in conn.execute(f"SELECT * FROM team_match_state WHERE match_id IN ({marks})", ids)}
    stories = {r["match_id"]: json.loads(r["story_json"]) for r in conn.execute(f"SELECT match_id, story_json FROM match_story WHERE match_id IN ({marks})", ids)}
    xi: dict[tuple[int, int], set[int]] = {}
    for r in conn.execute(f"SELECT match_id, team_id, player_id FROM player_match_state WHERE started = 1 AND match_id IN ({marks})", ids):
        xi.setdefault((r["match_id"], r["team_id"]), set()).add(r["player_id"])
    coach, coach_runs = {}, {}
    for r in conn.execute("SELECT mc.team_id, mc.coach_name, mi.status FROM match_coach mc JOIN match_intelligence mi ON mi.id = mc.match_id ORDER BY mi.kickoff_utc"):
        coach[r["team_id"]] = r["coach_name"]
        runs = coach_runs.setdefault(r["team_id"], [])
        if not runs or runs[-1]["name"] != r["coach_name"]:
            runs.append({"name": r["coach_name"], "finished": 0})
        if r["status"] == "FULL_TIME":
            runs[-1]["finished"] += 1

    acc: dict[int, dict] = {}
    for m in matches:
        story = stories.get(m["id"]) or {}
        for side, tid, oid, gf, ga in (("home", m["home_team_id"], m["away_team_id"], m["home_score"], m["away_score"]),
                                       ("away", m["away_team_id"], m["home_team_id"], m["away_score"], m["home_score"])):
            a = acc.setdefault(tid, {"n": 0, "pts": 0, "gf": 0, "ga": 0, "stats": [], "against": [], "formations": {}, "states": {}, "subs": [], "first_sub": [], "xis": [], "attack_subs": 0, "sub_n": 0})
            a["n"] += 1
            a["gf"] += gf or 0
            a["ga"] += ga or 0
            a["pts"] += 3 if (gf or 0) > (ga or 0) else 1 if gf == ga else 0
            own, opp = tms.get((m["id"], tid)), tms.get((m["id"], oid))
            if own is not None:
                a["stats"].append(own)
                if own["formation"]:
                    a["formations"][own["formation"]] = a["formations"].get(own["formation"], 0) + 1
            if opp is not None:
                a["against"].append(opp)
            for state, s in ((story.get("state_profile") or {}).get(side) or {}).items():
                t = a["states"].setdefault(state, {"minutes": 0.0, "xg_for": 0.0, "xg_against": 0.0})
                t["minutes"] += s.get("minutes") or 0
                t["xg_for"] += s.get("xg_for") or 0
                t["xg_against"] += s.get("xg_against") or 0
            subs = [s for s in story.get("subs") or [] if s.get("team_id") == tid]
            if subs:
                a["first_sub"].append(min(s["minute"] for s in subs))
                a["subs"] += [s["minute"] for s in subs]
                a["sub_n"] += len(subs)
                a["attack_subs"] += sum(1 for s in subs if "ATTACK" in str(s.get("kind", "")).upper())
            a["xis"].append(xi.get((m["id"], tid), set()))

    def mean(rows, col):
        vals = [r[col] for r in rows if r[col] is not None]
        return sum(vals) / len(vals) if vals else None

    out = {}
    for tid, a in acc.items():
        if tid not in teams:
            continue
        st, ag = a["stats"], a["against"]
        changes = [len(cur - prev) for prev, cur in zip(a["xis"], a["xis"][1:]) if prev and cur]
        states = {}
        for k, t in a["states"].items():
            ok = t["minutes"] >= MIN_STATE_MINUTES
            states[k] = {"minutes": round(t["minutes"]), "for90": round(90 * t["xg_for"] / t["minutes"], 2) if ok else None,
                         "against90": round(90 * t["xg_against"] / t["minutes"], 2) if ok else None}
        tackles = mean(st, "tackles")
        inter = mean(st, "interceptions")
        shots = mean(st, "shots")
        xg = mean(st, "xg")
        out[tid] = {
            "team_id": tid, "name": teams[tid]["name"], "short": teams[tid]["short_name"], "code": teams[tid]["code"],
            "manager": coach.get(tid), "manager_change": _manager_change(coach_runs.get(tid, [])), "played": a["n"], "points": a["pts"], "gf": a["gf"], "ga": a["ga"],
            "formation": max(a["formations"], key=a["formations"].get) if a["formations"] else None,
            "formations": dict(sorted(a["formations"].items(), key=lambda kv: -kv[1])),
            "m": {
                "xg_for": xg, "xg_against": mean(ag, "xg"), "possession": mean(st, "possession_pct"), "shots": shots,
                "xg_per_shot": xg / shots if xg is not None and shots else None, "big_chances": mean(st, "big_chances"),
                "box_touches": mean(st, "touches_opp_box"), "pass_accuracy": mean(st, "pass_accuracy_pct"),
                "ball_winning": (tackles or 0) + (inter or 0) if tackles is not None else None,
                "box_defending": (mean(st, "clearances") or 0) + (mean(st, "blocks") or 0) if st else None,
                "distance_km": mean(st, "distance_covered_m") / 1000 if mean(st, "distance_covered_m") else None,
                "sprints": mean(st, "sprints"), "corners": mean(st, "corners"), "shots_against": mean(ag, "shots"),
                "box_touches_against": mean(ag, "touches_opp_box"), "cards": mean(st, "yellow_cards"),
                "first_sub": median(a["first_sub"]) if a["first_sub"] else None,
                "rotation": sum(changes) / len(changes) if changes else None,
            },
            "states": states,
            "subs_per_match": round(a["sub_n"] / a["n"], 1) if a["n"] else None,
        }
    keys = {k for p in out.values() for k in p["m"]}
    pct = {k: _pct_rank({t: p["m"][k] for t, p in out.items()}) for k in keys}
    for k in ("leading", "trailing"):
        pct[f"{k}_push"] = _pct_rank({t: _push(p, k) for t, p in out.items()})
    for t, p in out.items():
        p["pct"] = {k: pct[k][t] for k in pct}
        p["m"] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in p["m"].items()}
        p["labels"] = _labels(p)
    return out


def _manager_change(runs: list[dict]) -> dict | None:
    """A new name on the sheet with fewer than five finished league matches: the style figures are mostly his predecessor's."""
    if len(runs) < 2 or runs[-1]["finished"] >= 5:
        return None
    return {"new": runs[-1]["name"], "previous": runs[-2]["name"], "matches": runs[-1]["finished"]}


def _push(p: dict, state: str) -> float | None:
    """xG for per 90 in this game state over xG for per 90 when level: above 1, the side attacks more in it."""
    s, lv = p["states"].get(state, {}), p["states"].get("level", {})
    if s.get("for90") is None or not lv.get("for90"):
        return None
    return s["for90"] / lv["for90"]


def _labels(p: dict) -> list[dict]:
    q = p["pct"]
    out = []

    def add(cond, text, tone, evidence):
        if cond:
            out.append({"text": text, "tone": tone, "evidence": evidence})

    m = p["m"]
    hi = lambda k, t=75: q.get(k) is not None and q[k] >= t
    lo = lambda k, t=25: q.get(k) is not None and q[k] <= t
    add(hi("possession"), "Keeps the ball", "neutral", f"{m['possession']:.0f}% possession" if m["possession"] else "")
    add(lo("possession"), "Plays without the ball", "neutral", f"{m['possession']:.0f}% possession" if m["possession"] else "")
    add(hi("ball_winning"), "Wins it back", "good", f"{m['ball_winning']:.0f} tackles + interceptions a match" if m["ball_winning"] else "")
    add(hi("box_defending") and lo("possession", 40), "Defends the box", "neutral", f"{m['box_defending']:.0f} clearances + blocks a match" if m["box_defending"] else "")
    add(hi("distance_km") or hi("sprints"), "Runs hard", "good", f"{m['distance_km'] or 0:.1f} km, {m['sprints'] or 0:.0f} sprints a match")
    add(hi("box_touches"), "Lives in the box", "good", f"{m['box_touches']:.0f} touches in the opposition box a match" if m["box_touches"] else "")
    add(hi("xg_per_shot"), "Shoots from good places", "good", f"{m['xg_per_shot']:.2f} xG a shot" if m["xg_per_shot"] else "")
    add(lo("xg_per_shot") and hi("shots", 50), "Shoots from distance", "bad", f"{m['xg_per_shot']:.2f} xG a shot" if m["xg_per_shot"] else "")
    add(lo("xg_against"), "Hard to create against", "good", f"{m['xg_against']:.2f} xG conceded a match" if m["xg_against"] else "")
    add(hi("xg_against"), "Opens up", "bad", f"{m['xg_against']:.2f} xG conceded a match" if m["xg_against"] else "")
    lead = _push(p, "leading")
    if lead is not None:
        add(q.get("leading_push") is not None and q["leading_push"] <= 25, "Sits on a lead", "neutral", f"attack {lead:.0%} of its level-score rate when ahead")
        add(q.get("leading_push") is not None and q["leading_push"] >= 75, "Keeps going when ahead", "good", f"attack {lead:.0%} of its level-score rate when ahead")
    trail = _push(p, "trailing")
    if trail is not None:
        add(q.get("trailing_push") is not None and q["trailing_push"] >= 75, "Chases hard when behind", "good", f"attack {trail:.0%} of its level-score rate when behind")
        add(q.get("trailing_push") is not None and q["trailing_push"] <= 25, "Flat when behind", "bad", f"attack {trail:.0%} of its level-score rate when behind")
    add(lo("first_sub"), "Early changes", "bad", f"first change at {m['first_sub']:.0f}' (median)" if m["first_sub"] else "")
    add(hi("first_sub"), "Late changes", "good", f"first change at {m['first_sub']:.0f}' (median)" if m["first_sub"] else "")
    add(hi("rotation"), "Rotates", "bad", f"{m['rotation']:.1f} changes to the eleven a match" if m["rotation"] is not None else "")
    add(lo("rotation"), "Settled eleven", "good", f"{m['rotation']:.1f} changes to the eleven a match" if m["rotation"] is not None else "")
    return out


def player_usage(conn: sqlite3.Connection, team_id: int | None = None, player_ids: list[int] | None = None) -> list[dict]:
    """How each player is used: starts, appearances off the bench, minutes when he starts, taken off before 60, full 90s."""
    ids = [m["id"] for m in _matches(conn)]
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    where, args = [f"s.match_id IN ({marks})"], list(ids)
    if team_id is not None:
        where.append("p.team_id = ?")
        args.append(team_id)
    if player_ids:
        where.append(f"s.player_id IN ({','.join('?' * len(player_ids))})")
        args += list(player_ids)
    rows: dict[int, dict] = {}
    team_matches: dict[int, int] = {}
    for r in conn.execute(
        f"SELECT s.player_id, p.web_name, p.team_id, et.singular_name_short AS pos, s.started, s.minutes, s.substituted_off_minute, s.substituted_on_minute, s.match_id "
        f"FROM player_match_state s JOIN players p ON p.id = s.player_id JOIN element_types et ON et.id = p.element_type WHERE {' AND '.join(where)}", args,
    ):
        u = rows.setdefault(r["player_id"], {"player_id": r["player_id"], "name": r["web_name"], "team_id": r["team_id"], "position": r["pos"],
                                              "starts": 0, "bench_apps": 0, "start_minutes": [], "hooked_before_60": 0, "full_90": 0, "off": []})
        if r["started"]:
            u["starts"] += 1
            mins = r["minutes"] or 0
            u["start_minutes"].append(mins)
            off = r["substituted_off_minute"]
            if off is not None:
                u["off"].append(off)
                if off < 60:
                    u["hooked_before_60"] += 1
            elif mins >= 89:
                u["full_90"] += 1
        elif r["substituted_on_minute"] is not None:
            u["bench_apps"] += 1
    for r in conn.execute(f"SELECT home_team_id AS t FROM match_intelligence WHERE id IN ({marks}) UNION ALL SELECT away_team_id FROM match_intelligence WHERE id IN ({marks})", ids + ids):
        team_matches[r["t"]] = team_matches.get(r["t"], 0) + 1
    out = []
    for u in rows.values():
        sm = u.pop("start_minutes")
        off = u.pop("off")
        u["club_matches"] = team_matches.get(u["team_id"], 0)
        u["avg_start_minutes"] = round(sum(sm) / len(sm)) if sm else None
        u["typical_off"] = round(median(off)) if off else None
        u["security"] = _security(u)
        out.append(u)
    out.sort(key=lambda u: (-u["starts"], u["hooked_before_60"]))
    return out


def _security(u: dict) -> str:
    n, s = u["club_matches"] or 0, u["starts"]
    if s == 0:
        return "bench" if u["bench_apps"] else "unused"
    share = s / n if n else 0
    if share >= 0.8 and u["hooked_before_60"] <= max(1, s // 5):
        return "nailed"
    if share >= 0.6:
        return "regular"
    return "rotation"


def dugout(conn: sqlite3.Connection) -> dict:
    profiles = club_profiles(conn)
    return {"clubs": sorted(profiles.values(), key=lambda p: (-p["points"], -(p["gf"] - p["ga"]))), "min_state_minutes": MIN_STATE_MINUTES}
