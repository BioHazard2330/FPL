"""THE MATCH ANALYST - a finished match read from its own shots, goals and substitutions.

Everything here is code over stored rows (`match_shots`, `match_events`,
`player_match_state`, `team_match_state`, FPL's own player status and news). No
LLM call. The output is a `story`: a score timeline, the share of each side's
chances by situation and zone, what each side did in each game state, where its
chances clustered in time, the result its shots deserved, every substitution
classified, one line per notable player, and a ranked list of findings in the
schema `ingestion.qualitative_analysis.apply_match_analysis` already accepts.

Assumptions, none of them fitted:
- Shot coordinates are metres on a 105 x 68 pitch with the attacking goal at
  x = 105 (FotMob's own). The penalty box is x >= 88.5 and 13.84 <= y <= 54.16,
  the six-yard box x >= 99.5 and 24.84 <= y <= 43.16.
- Game state is read at minute resolution: a shot or minute is "leading",
  "level" or "trailing" by the goals scored in strictly earlier minutes.
  Stoppage time is folded into minutes 45 and 90 and added to the last state.
- A goal credited to a side by a player the FPL table lists at the other club
  is an own goal. FotMob gives it no xG, so it counts in the score and in no
  shot total.
- A substitution is injury-linked only when the player came off and FPL's own
  status for him is now not "a" with news added after kickoff. The timing alone
  never makes the claim.
- Shots are independent when the deserved result is computed
  (`match_rebuild.deserved_result`).
- Thresholds below (a finding's minimum shots, shares and gaps) are judgements
  chosen to keep the list short. Nothing is tuned to a target.
"""
import json
import re
import sqlite3
from difflib import SequenceMatcher
import unicodedata
from bisect import bisect_left
from datetime import datetime, timezone

import numpy as np

from fpl_agent.models.match_rebuild import deserved_result

ENGINE_VERSION = "analyst-v1"

PEN_X, PEN_Y0, PEN_Y1 = 88.5, 13.84, 54.16
SIX_X, SIX_Y0, SIX_Y1 = 99.5, 24.84, 43.16
DEAD_BALL = frozenset({"SetPiece", "FromCorner", "FreeKick", "ThrowInSetPiece"})
OPEN_PLAY = frozenset({"RegularPlay", "IndividualPlay"})
BIG_CHANCE = 0.3
SPELL_MINUTES = 10
_NEWS_STATUSES = {"d": "doubtful", "i": "injured", "s": "suspended", "u": "unavailable", "n": "unavailable"}
_SUB_RE = re.compile(r"^(?P<on>.+?)\s+on for\s+(?P<off>.+)$")
_ASSIST_RE = re.compile(r"assist by (?P<name>[^)]+)\)")
_ADDED_RE = re.compile(r"\+\s*(\d+)\s*minutes? added")
_POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
_ATTACKING = {"MID", "FWD"}


def zone(x: float | None, y: float | None) -> str | None:
    if x is None or y is None:
        return None
    if x >= SIX_X and SIX_Y0 <= y <= SIX_Y1:
        return "six_yard"
    if x >= PEN_X and PEN_Y0 <= y <= PEN_Y1:
        return "box"
    return "outside"


def situation_group(situation: str | None) -> str:
    if situation in DEAD_BALL:
        return "dead_ball"
    if situation == "FastBreak":
        return "fast_break"
    if situation == "Penalty":
        return "penalty"
    return "open_play"


def _norm(text: str | None) -> str:
    folded = unicodedata.normalize("NFKD", text or "")
    return " ".join("".join(ch for ch in folded if not unicodedata.combining(ch)).lower().split())


def _fmt(value: float, places: int = 2) -> str:
    return f"{value:.{places}f}"


def _pct(value: float) -> str:
    return f"{round(100 * value)}%"


def _poss(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def _ordinal_minutes(start: int, end: int) -> str:
    return f"minute {start}" if start == end else f"minutes {start}-{end}"


def dedupe_events(events: list[dict]) -> tuple[list[dict], int]:
    """FotMob lists some substitutions twice, a minute apart. Keep the first."""
    kept: list[dict] = []
    seen: dict[tuple, int] = {}
    dropped = 0
    for e in sorted(events, key=lambda e: (e["minute"] or 0, e.get("id") or 0)):
        key = (e["type"], e["team_id"], _norm(e["description"]))
        last = seen.get(key)
        if e["type"] == "Substitution" and last is not None and (e["minute"] or 0) - last <= 2:
            dropped += 1
            continue
        seen[key] = e["minute"] or 0
        kept.append(e)
    return kept, dropped


def _name_index(players: dict[int, dict]) -> list[tuple[str, int]]:
    out = []
    for pid, p in players.items():
        for token in {_norm(p.get("web_name")), _norm(p.get("second_name"))}:
            if len(token) >= 3:
                out.append((token, pid))
    out.sort(key=lambda t: -len(t[0]))
    return out


def resolve_name(text: str, index: list[tuple[str, int]], team_of: dict[int, int] | None = None, team_id: int | None = None) -> int | None:
    folded = _norm(text)
    if not folded:
        return None
    for token, pid in index:
        if team_id is not None and team_of is not None and team_of.get(pid) != team_id:
            continue
        if token == folded or re.search(rf"(^|\s){re.escape(token)}($|\s)", folded):
            return pid
    return None


def _goal_timeline(events: list[dict], players: dict[int, dict], shots: list[dict], home_id: int, away_id: int) -> list[dict]:
    index = _name_index({pid: p for pid, p in players.items()})
    team_of = {pid: p.get("team_id") for pid, p in players.items()}
    pen_goal_minutes = {(s["minute"], s["team_id"]) for s in shots if s["situation"] == "Penalty" and s["outcome"] == "Goal"}
    out: list[dict] = []
    h = a = 0
    for e in events:
        if e["type"] != "Goal":
            continue
        credited_home = e["team_id"] == home_id
        scorer_team = (players.get(e["player_id"]) or {}).get("team_id")
        own_goal = e["player_id"] is not None and scorer_team is not None and scorer_team != e["team_id"]
        if credited_home:
            h += 1
        else:
            a += 1
        assist = None
        m = _ASSIST_RE.search(e["description"] or "")
        if m:
            assist = resolve_name(m.group("name"), index, team_of, e["team_id"])
        out.append({
            "minute": e["minute"], "side": "home" if credited_home else "away", "player_id": e["player_id"],
            "player_name": (players.get(e["player_id"]) or {}).get("web_name"),
            "own_goal": own_goal, "penalty": (e["minute"], e["team_id"]) in pen_goal_minutes and not own_goal,
            "assist_id": assist, "assist_name": m.group("name").strip() if m else None,
            "score": [h, a],
        })
    return out


def _score_before(goals: list[dict], minute: int) -> tuple[int, int]:
    h = a = 0
    for g in goals:
        if g["minute"] < minute:
            if g["side"] == "home":
                h += 1
            else:
                a += 1
    return h, a


def _state(score: tuple[int, int], side: str) -> str:
    own, opp = (score[0], score[1]) if side == "home" else (score[1], score[0])
    return "leading" if own > opp else "trailing" if own < opp else "level"


def _match_length(events: list[dict], shots: list[dict]) -> int:
    added = 0
    for e in events:
        if e["type"] == "AddedTime":
            m = _ADDED_RE.search(e["description"] or "")
            if m:
                added += int(m.group(1))
    last = max([e["minute"] or 0 for e in events] + [s["minute"] or 0 for s in shots] + [90])
    return max(90 + added, last)


def _side_of(team_id: int, home_id: int) -> str:
    return "home" if team_id == home_id else "away"


def _empty_state_row() -> dict:
    return {"minutes": 0.0, "xg_for": 0.0, "shots_for": 0, "xg_against": 0.0, "shots_against": 0}


def state_profile(goals: list[dict], shots: list[dict], home_id: int, length: int) -> dict:
    prof = {side: {s: _empty_state_row() for s in ("leading", "level", "trailing")} for side in ("home", "away")}
    final_goals = [g for g in goals]
    for k in range(1, length + 1):
        score = _score_before(final_goals, min(k, 91))
        if k > 90:
            score = _score_before(final_goals, 91)
        for side in ("home", "away"):
            prof[side][_state(score, side)]["minutes"] += 1
    for s in shots:
        if s["xg"] is None or s["minute"] is None:
            continue
        side = _side_of(s["team_id"], home_id)
        other = "away" if side == "home" else "home"
        score = _score_before(final_goals, s["minute"])
        prof[side][_state(score, side)]["xg_for"] += s["xg"]
        prof[side][_state(score, side)]["shots_for"] += 1
        prof[other][_state(score, other)]["xg_against"] += s["xg"]
        prof[other][_state(score, other)]["shots_against"] += 1
    for side in prof:
        for row in prof[side].values():
            row["xg_for"] = round(row["xg_for"], 3)
            row["xg_against"] = round(row["xg_against"], 3)
            row["per90_for"] = round(90 * row["xg_for"] / row["minutes"], 3) if row["minutes"] >= 5 else None
            row["per90_against"] = round(90 * row["xg_against"] / row["minutes"], 3) if row["minutes"] >= 5 else None
    return prof


def best_spell(shots: list[dict], team_id: int) -> dict | None:
    per_minute = np.zeros(100)
    for s in shots:
        if s["team_id"] == team_id and s["xg"] is not None and s["minute"] is not None:
            per_minute[min(s["minute"], 99)] += s["xg"]
    total = float(per_minute.sum())
    if total <= 0:
        return None
    window = np.convolve(per_minute, np.ones(SPELL_MINUTES), mode="valid")
    start = int(np.argmax(window))
    best = float(window[start])
    in_window = sum(
        1 for s in shots if s["team_id"] == team_id and s["xg"] is not None and s["minute"] is not None and start <= min(s["minute"], 99) < start + SPELL_MINUTES
    )
    return {"start": start, "end": start + SPELL_MINUTES - 1, "xg": round(best, 3), "share": round(best / total, 3), "shots": in_window}


def _side_metrics(shots: list[dict], team_id: int, opp_id: int, goals: list[dict], side: str, home_id: int) -> dict:
    mine = [s for s in shots if s["team_id"] == team_id and s["xg"] is not None]
    theirs = [s for s in shots if s["team_id"] == opp_id and s["xg"] is not None]

    def total(rows):
        return float(sum(s["xg"] for s in rows))

    def share(rows, pred):
        t = total(rows)
        return float(sum(s["xg"] for s in rows if pred(s)) / t) if t > 0 else None

    def by_group(rows):
        out = {}
        for g in ("open_play", "fast_break", "dead_ball", "penalty"):
            out[g] = round(total([s for s in rows if situation_group(s["situation"]) == g]), 3)
        return out

    mine_xg, theirs_xg = total(mine), total(theirs)
    goals_for = sum(1 for g in goals if g["side"] == side and not g["own_goal"])
    own_goals_for = sum(1 for g in goals if g["side"] == side and g["own_goal"])
    conceded_open = sum(1 for g in goals if g["side"] != side and not g["own_goal"])
    ot_for = [s for s in mine if s["on_target"]]
    ot_against = [s for s in theirs if s["on_target"]]
    xgot_for = float(sum((s["xgot"] or 0.0) for s in ot_for))
    xgot_against = float(sum((s["xgot"] or 0.0) for s in ot_against))
    half = lambda rows, h: total([s for s in rows if (s["minute"] or 0) > 45] if h == 2 else [s for s in rows if (s["minute"] or 0) <= 45])  # noqa: E731
    return {
        "shots": len(mine), "xg": round(mine_xg, 3), "xg_per_shot": round(mine_xg / len(mine), 3) if mine else None,
        "shots_on_target": len(ot_for), "xgot": round(xgot_for, 3),
        "xg_against": round(theirs_xg, 3), "shots_against": len(theirs), "xgot_against": round(xgot_against, 3),
        "shots_on_target_against": len(ot_against),
        "goals": goals_for, "own_goals_for": own_goals_for, "goals_conceded_excl_og": conceded_open,
        "goals_minus_xg": round(goals_for - mine_xg, 3),
        "conceded_minus_xga": round(conceded_open - theirs_xg, 3),
        "xg_by_situation": by_group(mine), "xga_by_situation": by_group(theirs),
        "dead_ball_xg_share": share(mine, lambda s: situation_group(s["situation"]) == "dead_ball"),
        "dead_ball_xga_share": share(theirs, lambda s: situation_group(s["situation"]) == "dead_ball"),
        "dead_ball_shots": sum(1 for s in mine if situation_group(s["situation"]) == "dead_ball"),
        "dead_ball_shots_against": sum(1 for s in theirs if situation_group(s["situation"]) == "dead_ball"),
        "fast_break_xg_share": share(mine, lambda s: situation_group(s["situation"]) == "fast_break"),
        "header_xg_share": share(mine, lambda s: s["shot_type"] == "Header"),
        "box_xg_share": share(mine, lambda s: zone(s["x"], s["y"]) in ("box", "six_yard")),
        "outside_box_shot_share": (sum(1 for s in mine if zone(s["x"], s["y"]) == "outside") / len(mine)) if mine else None,
        "big_chances": sum(1 for s in mine if s["xg"] >= BIG_CHANCE),
        "big_chances_scored": sum(1 for s in mine if s["xg"] >= BIG_CHANCE and s["outcome"] == "Goal"),
        "woodwork": sum(1 for s in mine if s["outcome"] == "Post"),
        "woodwork_xg": round(float(sum(s["xg"] for s in mine if s["outcome"] == "Post")), 3),
        "first_half_xg_share": (half(mine, 1) / mine_xg) if mine_xg > 0 else None,
        "own_goals_for_count": own_goals_for,
    }


def _player_lines(shots: list[dict], pms: list[dict], players: dict[int, dict], home_id: int, goals: list[dict]) -> list[dict]:
    lines: dict[int, dict] = {}
    for row in pms:
        pid = row["player_id"]
        if pid is None:
            continue
        lines[pid] = {
            "player_id": pid, "name": (players.get(pid) or {}).get("web_name"), "team_id": row["team_id"],
            "side": _side_of(row["team_id"], home_id), "position": (players.get(pid) or {}).get("position"),
            "started": bool(row["started"]), "minutes": row["minutes"], "on_minute": row["on_min"], "off_minute": row["off_min"],
            "goals": row["goals"] or 0, "assists": row["assists"] or 0, "xa": row["xa"], "rating": row["rating"],
            "shots": 0, "xg": 0.0, "dead_ball_shots": 0, "fast_break_shots": 0, "header_shots": 0, "box_shots": 0,
            "situations": {}, "shot_minutes": [], "biggest_chance": None, "penalty_shots": 0,
        }
    for s in shots:
        pid = s["player_id"]
        if pid is None or s["xg"] is None or pid not in lines:
            continue
        line = lines[pid]
        line["shots"] += 1
        line["xg"] += s["xg"]
        group = situation_group(s["situation"])
        line["situations"][s["situation"] or "?"] = line["situations"].get(s["situation"] or "?", 0) + 1
        line["dead_ball_shots"] += group == "dead_ball"
        line["fast_break_shots"] += group == "fast_break"
        line["penalty_shots"] += group == "penalty"
        line["header_shots"] += s["shot_type"] == "Header"
        line["box_shots"] += zone(s["x"], s["y"]) in ("box", "six_yard")
        line["shot_minutes"].append(s["minute"])
        if line["biggest_chance"] is None or s["xg"] > line["biggest_chance"]["xg"]:
            line["biggest_chance"] = {"xg": round(s["xg"], 3), "minute": s["minute"], "situation": s["situation"], "outcome": s["outcome"]}
    for line in lines.values():
        line["xg"] = round(line["xg"], 3)
    return sorted(lines.values(), key=lambda l: (-l["xg"], -l["goals"]))


def classify_subs(
    sub_events: list[dict], goals: list[dict], players: dict[int, dict], pms: list[dict], home_id: int,
    status_after: dict[int, dict],
) -> list[dict]:
    index = _name_index(players)
    team_of = {pid: p.get("team_id") for pid, p in players.items()}
    off_candidates: dict[tuple[int, int], list[int]] = {}
    for row in pms:
        if row["player_id"] is not None and row["off_min"] is not None:
            off_candidates.setdefault((row["team_id"], row["off_min"]), []).append(row["player_id"])
    by_minute_count: dict[tuple[int, int], int] = {}
    for e in sub_events:
        by_minute_count[(e["team_id"], e["minute"])] = by_minute_count.get((e["team_id"], e["minute"]), 0) + 1

    out = []
    for e in sub_events:
        m = _SUB_RE.match((e["description"] or "").strip())
        if not m:
            continue
        side = _side_of(e["team_id"], home_id)
        on_id = e["player_id"]
        off_id = resolve_name(m.group("off"), index, team_of, e["team_id"])
        if off_id is None:
            pool = off_candidates.get((e["team_id"], e["minute"]), [])
            if len(pool) == 1:
                off_id = pool[0]
            elif pool:
                target = _norm(m.group("off"))
                scored = sorted(
                    ((SequenceMatcher(None, target, _norm(f"{players[c].get('first_name') or ''} {players[c].get('second_name') or ''} {players[c].get('web_name') or ''}")).ratio(), c)
                     for c in pool if c in players),
                    reverse=True,
                )
                if scored and scored[0][0] >= 0.45:
                    off_id = scored[0][1]
        on_pos = (players.get(on_id) or {}).get("position")
        off_pos = (players.get(off_id) or {}).get("position")
        score = _score_before(goals, (e["minute"] or 0) + 1)
        own, opp = (score[0], score[1]) if side == "home" else (score[1], score[0])
        margin = own - opp
        off_player = players.get(off_id) or {}
        change = status_after.get(off_id) if off_id is not None else None
        injury_linked = bool(change and change["status"] in ("d", "i", "u"))
        minute = e["minute"] or 0
        group = by_minute_count[(e["team_id"], minute)]
        if injury_linked:
            kind = "INJURY_LINKED"
            note = f"{off_player.get('web_name')} flagged {_NEWS_STATUSES[change['status']]} by FPL after the match" + (f": {change['news']}" if change.get("news") else "")
        elif minute <= 36:
            kind, note = "EARLY_UNEXPLAINED", "before minute 37 with no FPL news on the player who came off"
        elif minute in (45, 46):
            kind, note = "HALF_TIME", "made at the interval"
        elif margin >= 2 and minute >= 60:
            kind, note = "MANAGED_MINUTES", f"leading by {margin} at minute {minute}"
        elif margin <= -1 and on_pos in _ATTACKING and off_pos is not None and off_pos != on_pos and (off_pos == "DEF" or (off_pos == "MID" and on_pos == "FWD")):
            kind, note = "CHASING", f"trailing by {-margin}; {off_pos} replaced by {on_pos}"
        elif margin == 1 and minute >= 75 and on_pos == "DEF" and off_pos in _ATTACKING:
            kind, note = "PROTECTING_LEAD", f"leading by 1 at minute {minute}; {off_pos} replaced by DEF"
        elif on_pos is not None and on_pos == off_pos:
            kind, note = "LIKE_FOR_LIKE", f"{on_pos} for {off_pos}, score margin {margin:+d}"
        else:
            kind, note = "TACTICAL", f"score margin {margin:+d}; {off_pos or '?'} replaced by {on_pos or '?'}"
        out.append({
            "minute": minute, "side": side, "team_id": e["team_id"], "on_id": on_id, "on": (players.get(on_id) or {}).get("web_name") or m.group("on"),
            "off_id": off_id, "off": off_player.get("web_name") or m.group("off"), "on_position": on_pos, "off_position": off_pos,
            "margin": margin, "kind": kind, "note": note, "simultaneous_changes": group,
        })
    return out


def league_profile(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT s.match_id, s.team_id, s.situation, s.shot_type, s.xg FROM match_shots s "
        "JOIN match_intelligence m ON m.id = s.match_id WHERE m.status = 'FULL_TIME' AND s.xg IS NOT NULL"
    ).fetchall()
    per: dict[tuple[int, int], dict] = {}
    all_xg = all_dead = 0.0
    group_xg = {"open_play": 0.0, "fast_break": 0.0, "dead_ball": 0.0, "penalty": 0.0}
    for r in rows:
        group_xg[situation_group(r["situation"])] += r["xg"]
        cell = per.setdefault((r["match_id"], r["team_id"]), {"xg": 0.0, "dead": 0.0, "header": 0.0, "shots": 0})
        cell["xg"] += r["xg"]
        cell["shots"] += 1
        if r["situation"] in DEAD_BALL:
            cell["dead"] += r["xg"]
            all_dead += r["xg"]
        if r["shot_type"] == "Header":
            cell["header"] += r["xg"]
        all_xg += r["xg"]
    dead_shares = sorted(c["dead"] / c["xg"] for c in per.values() if c["xg"] >= 0.3)
    xg_totals = sorted(c["xg"] for c in per.values())
    return {
        "dead_ball_share": all_dead / all_xg if all_xg else None,
        "group_share": {k: (v / all_xg if all_xg else None) for k, v in group_xg.items()},
        "dead_ball_shares_sorted": dead_shares,
        "xg_totals_sorted": xg_totals,
        "team_matches": len(per),
        "xg_per_shot": all_xg / len(rows) if rows else None,
    }


def _percentile(sorted_values: list[float], value: float) -> float | None:
    if not sorted_values:
        return None
    return bisect_left(sorted_values, value) / len(sorted_values)


def _player_ref(line: dict) -> str:
    return line.get("name") or "player"


def _find_players_status(pms: list[dict], players: dict[int, dict], status_after: dict[int, dict]) -> list[dict]:
    flags = []
    for row in pms:
        pid = row["player_id"]
        change = status_after.get(pid) if pid is not None else None
        if change is None:
            continue
        flags.append({
            "player_id": pid, "name": (players.get(pid) or {}).get("web_name"), "team_id": row["team_id"], "status": change["status"],
            "label": _NEWS_STATUSES.get(change["status"], change["status"]), "news": change.get("news"), "minutes": row["minutes"],
            "off_minute": row["off_min"], "detected_at": change["detected_at"],
        })
    return flags


def build_story(inputs: dict, league: dict | None = None) -> dict:
    match = inputs["match"]
    home_id, away_id = match["home_id"], match["away_id"]
    players = inputs["players"]
    shots_all = inputs["shots"]
    shots = [s for s in shots_all if s["xg"] is not None]
    events, dropped = dedupe_events(inputs["events"])
    goals = _goal_timeline(events, players, shots_all, home_id, away_id)
    length = _match_length(events, shots_all)
    consistent = (
        len([g for g in goals if g["side"] == "home"]) == match["home_score"]
        and len([g for g in goals if g["side"] == "away"]) == match["away_score"]
    )
    names = {home_id: match["home_name"], away_id: match["away_name"]}
    sides = {"home": home_id, "away": away_id}
    metrics = {side: _side_metrics(shots_all, sides[side], sides["away" if side == "home" else "home"], goals, side, home_id) for side in sides}

    home_xgs = [s["xg"] for s in shots if s["team_id"] == home_id]
    away_xgs = [s["xg"] for s in shots if s["team_id"] == away_id]
    deserved = deserved_result(home_xgs, away_xgs) if shots else None
    if deserved:
        deserved = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in deserved.items()}
        hs, as_ = match["home_score"], match["away_score"]
        actual_home = 3 if hs > as_ else 1 if hs == as_ else 0
        actual_away = 3 if as_ > hs else 1 if hs == as_ else 0
        deserved["actual_home_points"], deserved["actual_away_points"] = actual_home, actual_away

    profile = state_profile(goals, shots_all, home_id, length) if consistent else None
    spells = {side: best_spell(shots_all, sides[side]) for side in sides}
    lines = _player_lines(shots_all, inputs["pms"], players, home_id, goals)
    sub_events = [e for e in events if e["type"] == "Substitution"]
    subs = classify_subs(sub_events, goals, players, inputs["pms"], home_id, inputs.get("status_after", {}))
    status_flags = _find_players_status(inputs["pms"], players, inputs.get("status_after", {}))
    missed_pens = [e for e in events if e["type"] == "MissedPenalty"]

    ctx = {
        "match": match, "names": names, "sides": sides, "metrics": metrics, "deserved": deserved, "profile": profile,
        "spells": spells, "lines": lines, "subs": subs, "goals": goals, "players": players, "shots": shots,
        "status_flags": status_flags, "league": league or {}, "length": length, "home_id": home_id,
        "missed_pens": missed_pens, "events": events, "consistent": consistent, "pms": inputs["pms"],
        "team_state_xg": inputs.get("team_state_xg", {}),
    }
    findings = _findings(ctx)
    findings.sort(key=lambda f: -f["rank"])
    for f in findings:
        f["name"] = names.get(f["subject_id"]) if f["subject_type"] == "team" else (players.get(f["subject_id"]) or {}).get("web_name")
    headline = _headline(ctx, findings)
    uncertainties = _uncertainties(ctx, dropped)

    compact_shots = [
        {"m": s["minute"], "side": _side_of(s["team_id"], home_id), "x": s["x"], "y": s["y"], "xg": round(s["xg"], 3),
         "xgot": s["xgot"], "o": s["outcome"], "sit": s["situation"], "type": s["shot_type"], "pid": s["player_id"],
         "name": s["player_name"], "zone": zone(s["x"], s["y"])}
        for s in sorted(shots_all, key=lambda s: (s["minute"] or 0))
        if s["xg"] is not None
    ]
    return {
        "version": ENGINE_VERSION, "match_id": match["id"], "consistent": consistent, "length": length,
        "headline": headline, "uncertainties": uncertainties,
        "match": {
            "home": {"team_id": home_id, "name": match["home_name"], "score": match["home_score"]},
            "away": {"team_id": away_id, "name": match["away_name"], "score": match["away_score"]},
            "kickoff": match.get("kickoff"),
        },
        "metrics": metrics, "deserved": deserved, "state_profile": profile, "spells": spells,
        "timeline": goals, "subs": subs, "players": lines[:14], "status_flags": status_flags,
        "cards": [
            {"minute": e["minute"], "side": _side_of(e["team_id"], home_id), "player_id": e["player_id"], "name": (players.get(e["player_id"]) or {}).get("web_name")}
            for e in events if e["type"] == "Card"
        ],
        "shots": compact_shots, "findings": findings, "duplicate_events_dropped": dropped,
        "team_state": {str(k): v for k, v in (inputs.get("team_state") or {}).items()},
        "league": {"group_share": (league or {}).get("group_share"), "xg_per_shot": (league or {}).get("xg_per_shot"), "team_matches": (league or {}).get("team_matches")},
    }


def _uncertainties(ctx: dict, dropped: int) -> str:
    parts = ["One match."]
    if not ctx["consistent"]:
        parts.append("The goal timeline does not add up to the final score, so game-state splits were not computed.")
    own = [g for g in ctx["goals"] if g["own_goal"]]
    if own:
        parts.append(f"{len(own)} own goal(s) count in the score and carry no xG.")
    if dropped:
        parts.append(f"{dropped} duplicate substitution event(s) were counted once.")
    ts = ctx.get("team_state_xg") or {}
    diffs = [f"{ctx['names'][tid]} {_fmt(ctx['metrics'][side]['xg'])} against FotMob's team figure {_fmt(ts[tid])}" for side, tid in ctx["sides"].items()
             if ts.get(tid) is not None and abs(ts[tid] - ctx["metrics"][side]["xg"]) >= 0.15]
    if diffs:
        parts.append("Shot-sum xG differs from FotMob's team xG: " + "; ".join(diffs) + ".")
    if ctx["status_flags"]:
        parts.append("Fitness flags are FPL status changes seen within 48 hours of kickoff.")
    parts.append("Game state is read at minute resolution; shots are treated as independent when the result is replayed.")
    return " ".join(parts)


def _finding(subject_type: str, subject_id: int, otype: str, observed: str, inferred: str, direction: str | None, signal: str | None,
             reason: str | None, confidence: str, evidence: str, rank: float, short: str | None = None, metric: str | None = None) -> dict:
    return {
        "subject_type": subject_type, "subject_id": subject_id, "observation_type": otype, "observed": observed,
        "inferred": inferred, "fpl_direction": direction, "fpl_signal": signal, "fpl_reason": reason,
        "confidence": confidence, "evidence_ref": evidence, "rank": round(rank, 3), "short": short, "metric": metric,
    }


def _findings(ctx: dict) -> list[dict]:
    out: list[dict] = []
    out += _team_findings(ctx)
    out += _player_findings(ctx)
    out += _sub_findings(ctx)
    return out


def _team_findings(ctx: dict) -> list[dict]:
    m, names, sides, metrics, league = ctx["match"], ctx["names"], ctx["sides"], ctx["metrics"], ctx["league"]
    out: list[dict] = []
    for side in ("home", "away"):
        opp_side = "away" if side == "home" else "home"
        tid, oid = sides[side], sides[opp_side]
        me, them = metrics[side], metrics[opp_side]
        name, oname = names[tid], names[oid]
        score_for = m["home_score"] if side == "home" else m["away_score"]
        score_against = m["away_score"] if side == "home" else m["home_score"]
        dead_share = me["dead_ball_xg_share"]
        dead_pct = _percentile(league.get("dead_ball_shares_sorted", []), dead_share) if dead_share is not None else None
        league_dead = league.get("dead_ball_share")
        if dead_share is not None and me["dead_ball_shots"] >= 4 and dead_share >= 0.5 and me["dead_ball_shots"] / me["shots"] >= 0.4 and (dead_pct is None or dead_pct >= 0.85):
            lg = f" against a league figure of {_pct(league_dead)}" if league_dead is not None else ""
            sit = me["xg_by_situation"]["dead_ball"]
            out.append(_finding(
                "team", tid, "TEAM_PATTERN",
                f"{me['dead_ball_shots']} of {me['shots']} shots and {_fmt(sit)} of {_fmt(me['xg'])} xG ({_pct(dead_share)}) came from corners, free kicks, set pieces and throw-ins{lg}",
                f"{_poss(name)} chances came from dead balls, not open play ({_fmt(me['xg_by_situation']['open_play'])} xG in open play, {_fmt(me['xg_by_situation']['fast_break'])} on the break).",
                "WATCH", "SET_PIECES", f"{_pct(dead_share)} of {name}'s xG from set plays in one match", "medium",
                f"team xg by situation, {me['dead_ball_shots']} dead-ball shots", 0.6 + dead_share + (0.2 if dead_pct and dead_pct >= 0.95 else 0),
                short=f"{_pct(dead_share)} of {_poss(name)} xG from dead balls", metric="dead_ball_xg_share",
            ))
        conc_share = me["dead_ball_xga_share"]
        if conc_share is not None and me["dead_ball_shots_against"] >= 4 and conc_share >= 0.55 and me["xg_against"] >= 0.6:
            out.append(_finding(
                "team", tid, "DEFENSIVE_ROLE",
                f"{name} conceded {me['dead_ball_shots_against']} of {me['shots_against']} shots and {_fmt(them['xg_by_situation']['dead_ball'])} of {_fmt(me['xg_against'])} xG ({_pct(conc_share)}) from dead balls",
                "The chances against came from set plays; open-play defending conceded "
                f"{_fmt(them['xg_by_situation']['open_play'])} xG.",
                "WATCH", "SET_PIECES", f"set-piece exposure: {_pct(conc_share)} of xG conceded", "low",
                f"team xga by situation, {me['dead_ball_shots_against']} dead-ball shots against", 0.45 + conc_share / 2,
                metric="dead_ball_xga_share",
            ))
        actual_pts = 3 if score_for > score_against else 1 if score_for == score_against else 0
        if ctx["deserved"]:
            d = ctx["deserved"]
            xpts = d["home_points"] if side == "home" else d["away_points"]
            win_p = d["home_win"] if side == "home" else d["away_win"]
            gap = actual_pts - xpts
            if abs(gap) >= 1.2:
                direction = "NEUTRAL"
                verb = "ran ahead of" if gap > 0 else "fell short of"
                out.append(_finding(
                    "team", tid, "TEAM_PATTERN",
                    f"{name} {score_for}-{score_against} {oname}: {actual_pts} points against {_fmt(xpts, 1)} deserved from the shots ({_fmt(me['xg'])} xG for, {_fmt(me['xg_against'])} against; replayed, {name} win {_pct(win_p)})",
                    f"The result {verb} the chances by {_fmt(abs(gap), 1)} points.",
                    direction, "TEAM_ATTACK" if score_for else "FIXTURES", f"{_fmt(me['xg'])} xG for and {_fmt(me['xg_against'])} against is the repeatable measure; the score is not",
                    "medium", "deserved_result over shot xG", 0.5 + abs(gap) / 3,
                    short=f"{actual_pts} points from {_fmt(xpts, 1)} deserved ({_fmt(me['xg'])} xG to {_fmt(me['xg_against'])})" if abs(gap) >= 1.2 else None,
                ))
        gap = me["goals"] - me["xg"]
        if abs(gap) >= 1.2 and me["shots"] >= 5:
            low_xg_goals = sorted([s for s in ctx["shots"] if s["team_id"] == tid and s["outcome"] == "Goal"], key=lambda s: s["xg"])[:3]
            if gap > 0:
                detail = ", ".join(f"minute {s['minute']} at {_fmt(s['xg'])} xG" for s in low_xg_goals)
                text = f"{name} scored {me['goals']} goal{'s' if me['goals'] != 1 else ''} from {_fmt(me['xg'])} xG{' (own goal not counted)' if me['own_goals_for'] else ''}; lowest-xG goals: {detail}"
                inferred = f"Scoring ran {_fmt(gap, 1)} goals above the chances created."
                direction, reason = "NEUTRAL", "finishing above xG does not project forward in one match"
            else:
                text = f"{name} scored {me['goals']} from {_fmt(me['xg'])} xG over {me['shots']} shots ({me['big_chances']} chances of {_fmt(BIG_CHANCE, 1)} xG or more, {me['big_chances_scored']} scored)"
                inferred = f"Scoring ran {_fmt(-gap, 1)} goals below the chances created" + (f", with {me['woodwork']} shots off the woodwork ({_fmt(me['woodwork_xg'])} xG)." if me["woodwork"] else ".")
                direction, reason = "WATCH", "chances were created; the finishing shortfall is the variable part"
            out.append(_finding(
                "team", tid, "TEAM_PATTERN", text, inferred, direction, "TEAM_ATTACK", reason, "medium", "goals vs xG", 0.5 + abs(gap) / 3,
                short=f"{name} {me['goals']} goals from {_fmt(me['xg'])} xG", metric="goals_minus_xg",
            ))
        if me["shots_against"] <= 4 and me["xg_against"] <= 0.35 and me["shots"] >= 8:
            out.append(_finding(
                "team", tid, "DEFENSIVE_ROLE",
                f"{oname} had {me['shots_against']} shots, {_fmt(me['xg_against'])} xG, {me['shots_on_target_against']} on target",
                f"{name} gave {oname} almost no chances while creating {_fmt(me['xg'])} xG.", "POSITIVE", "TEAM_ATTACK",
                f"{_fmt(me['xg_against'])} xG conceded", "medium", "shots against", 0.45 + (0.4 - me["xg_against"]),
                short=f"{oname} held to {me['shots_against']} shots and {_fmt(me['xg_against'])} xG",
            ))
        spell = ctx["spells"][side]
        if spell and spell["share"] >= 0.55 and spell["xg"] >= 0.5 and me["shots"] >= 5:
            out.append(_finding(
                "team", tid, "TEAM_PATTERN",
                f"{_fmt(spell['xg'])} of {_poss(name)} {_fmt(me['xg'])} xG ({_pct(spell['share'])}) came in {_ordinal_minutes(spell['start'], spell['end'])}",
                f"The other {me['shots'] - spell['shots']} shots produced {_fmt(me['xg'] - spell['xg'])} xG.",
                "NEUTRAL", "TEAM_ATTACK", f"output concentrated in one {SPELL_MINUTES}-minute spell", "low",
                f"best {SPELL_MINUTES}-minute window", 0.35 + spell["share"] / 2,
                short=f"{_pct(spell['share'])} of {_poss(name)} xG in {_ordinal_minutes(spell['start'], spell['end'])}", metric="best_spell_share",
            ))
        if ctx["profile"]:
            prof = ctx["profile"][side]
            lead = prof["leading"]
            other_minutes = prof["level"]["minutes"] + prof["trailing"]["minutes"]
            other_xg = prof["level"]["xg_for"] + prof["trailing"]["xg_for"]
            if lead["minutes"] >= 25 and lead["shots_for"] + prof["level"]["shots_for"] + prof["trailing"]["shots_for"] >= 8 and other_minutes >= 5:
                lead_rate = lead["per90_for"]
                other_rate = 90 * other_xg / other_minutes
                if lead_rate is not None and (lead_rate > 1.5 * max(other_rate, 0.2) and lead["xg_for"] >= 1.0):
                    out.append(_finding(
                        "team", tid, "TEAM_PATTERN",
                        f"{name} led for {int(lead['minutes'])} of {ctx['length']} minutes and created {_fmt(lead['xg_for'])} of {_fmt(me['xg'])} xG while ahead ({_fmt(lead_rate, 1)} per 90, against {_fmt(other_rate, 1)} per 90 level or behind)",
                        f"{oname} was chasing the game for those minutes, so the chance count after the first goals reflects the match state as much as {name}'s attack.",
                        "NEUTRAL", "TEAM_ATTACK", "chances created while leading carry less weight", "medium", "xg by game state", 0.4 + min(lead["xg_for"], 2.5) / 5,
                        short=f"{name} created {_fmt(lead['xg_for'])} of {_fmt(me['xg'])} xG while leading",
                    ))
        early = [g for g in ctx["goals"] if g["side"] == side and (g["minute"] or 0) <= 20]
        if len(early) >= 2:
            goal_xg = sum(
                s["xg"] for s in ctx["shots"]
                if s["team_id"] == tid and s["outcome"] == "Goal" and (s["minute"] or 0) <= 20
            )
            if goal_xg <= 0.5:
                last_min = max(g["minute"] for g in early)
                og = sum(1 for g in early if g["own_goal"])
                og_text = f" ({og} an own goal)" if og else ""
                out.append(_finding(
                    "team", tid, "TEAM_PATTERN",
                    f"{len(early)} goals by minute {last_min}{og_text} from shots worth {_fmt(goal_xg)} xG",
                    f"{oname} trailed from the opening minutes, so the rest of the match was played with the result set by low-xG events.",
                    "NEUTRAL", "TEAM_ATTACK", "an early lead built on low-xG goals changes how both sides play the remainder", "medium",
                    "goal timeline and goal-shot xG", 0.55 + len(early) / 10, short=f"{len(early)} goals by minute {last_min} from {_fmt(goal_xg)} xG",
                ))
        late = [s for s in ctx["shots"] if s["team_id"] == tid and (s["minute"] or 0) >= 60]
        late_headers = [s for s in late if s["shot_type"] == "Header"]
        if len(late) >= 5 and len(late_headers) / len(late) >= 0.7:
            out.append(_finding(
                "team", tid, "TACTICAL_CHANGE",
                f"{len(late_headers)} of {_poss(name)} {len(late)} shots from minute 60 were headers ({_fmt(sum(s['xg'] for s in late_headers))} xG)",
                f"{name} went to crosses and long balls while the score was {score_for}-{score_against}.",
                "WATCH", "TACTICAL_CHANGE", "late chances all aerial", "low", "shot types from minute 60", 0.4,
            ))
        if me["woodwork"] >= 2:
            out.append(_finding(
                "team", tid, "TEAM_PATTERN",
                f"{me['woodwork']} {name} shots hit the woodwork, worth {_fmt(me['woodwork_xg'])} xG", f"The shots that came back off the post or bar were chances of that size.",
                "NEUTRAL", "TEAM_ATTACK", "woodwork is variance", "low", "shot outcomes", 0.3 + me["woodwork_xg"],
            ))
        if me["xgot_against"] - me["goals_conceded_excl_og"] >= 1.2 and me["shots_on_target_against"] >= 3:
            out.append(_finding(
                "team", tid, "DEFENSIVE_ROLE",
                f"{oname} put {me['shots_on_target_against']} shots on target worth {_fmt(me['xgot_against'])} xGOT and scored {me['goals_conceded_excl_og']}",
                f"{_poss(name)} goalkeeper kept out {_fmt(me['xgot_against'] - me['goals_conceded_excl_og'], 1)} goals more than the on-target shots implied.",
                "POSITIVE", "TEAM_ATTACK", "shot-stopping beat the xGOT faced", "low", "xgot against vs goals conceded", 0.4,
            ))
    own_goals = [g for g in ctx["goals"] if g["own_goal"]]
    for g in own_goals:
        scorer = ctx["players"].get(g["player_id"]) or {}
        side = g["side"]
        tid = ctx["sides"][side]
        out.append(_finding(
            "team", tid, "TEAM_PATTERN",
            f"Minute {g['minute']}: own goal by {scorer.get('web_name', 'a ' + ctx['names'][ctx['sides']['away' if side == 'home' else 'home']] + ' player')}, credited to {ctx['names'][tid]}",
            "The goal carries no xG, so the shot totals do not include it.", "NEUTRAL", "TEAM_ATTACK",
            "an own goal gives no attacking credit to anyone", "high", "goal timeline vs player club", 0.55,
        ))
    return out


def _player_findings(ctx: dict) -> list[dict]:
    out: list[dict] = []
    team_xg = {side: ctx["metrics"][side]["xg"] for side in ("home", "away")}
    lines = ctx["lines"]
    shots = ctx["shots"]
    goals = ctx["goals"]
    volume_done: set[int] = set()
    for line in lines:
        pid = line["player_id"]
        name = _player_ref(line)
        pos = line.get("position") or "?"
        mins = line["minutes"]
        mins_text = f"{mins} minutes" if mins is not None else "minutes unknown"
        team_total = team_xg[line["side"]] or 0.0
        my_goals = [s for s in shots if s["player_id"] == pid and s["outcome"] == "Goal"]
        if line["penalty_shots"]:
            pen = [s for s in shots if s["player_id"] == pid and s["situation"] == "Penalty"]
            outcome = ", ".join(f"minute {s['minute']} {('scored' if s['outcome'] == 'Goal' else 'missed or saved')}" for s in pen)
            out.append(_finding(
                "player", pid, "SET_PIECE", f"Took {len(pen)} penalt{'y' if len(pen) == 1 else 'ies'}: {outcome} ({_fmt(sum(s['xg'] for s in pen))} xG)",
                f"{name} was the penalty taker in this match.", "POSITIVE", "SET_PIECES", "penalty duty seen taking a kick", "medium", "shot situation Penalty", 0.7,
            ))
        if line["goals"] >= 1 and line["shots"] >= 1 and my_goals:
            low = [s for s in my_goals if s["xg"] <= 0.05 and s["situation"] != "Penalty"]
            if low and line["xg"] <= 0.2:
                where = ", ".join(f"minute {s['minute']} at {_fmt(s['xg'])} xG" for s in low)
                out.append(_finding(
                    "player", pid, "ATTACKING_ROLE", f"{line['goals']} goal from {line['shots']} shot ({_fmt(line['xg'])} xG), {where}, {mins_text}",
                    "A finish from very low odds; the shot quality says nothing about a repeatable chance.", "NEUTRAL", "GOAL_THREAT",
                    f"scored from {_fmt(min(s['xg'] for s in low))} xG; do not project", "high", "goal shots", 0.5,
                ))
                continue
        if line["shots"] >= 4 or line["xg"] >= 0.6:
            per_shot = line["xg"] / line["shots"] if line["shots"] else 0.0
            bits = []
            if line["fast_break_shots"] >= 2:
                bits.append(f"{line['fast_break_shots']} on the break")
            if line["dead_ball_shots"] >= 2:
                bits.append(f"{line['dead_ball_shots']} from set plays")
            if line["header_shots"] >= 2:
                bits.append(f"{line['header_shots']} headers")
            bits.append(f"{line['box_shots']} of {line['shots']} inside the box")
            goal_part = f"{line['goals']} goal{'s' if line['goals'] != 1 else ''}" if line["goals"] else "no goal"
            assist_part = f", {line['assists']} assist{'s' if line['assists'] != 1 else ''}" if line["assists"] else ""
            share = line["xg"] / team_total if team_total else 0.0
            quality = "low-value volume" if per_shot < 0.07 else "chance quality per shot above the league average" if per_shot >= 0.15 else "mid-value volume"
            direction = "POSITIVE" if line["xg"] >= 0.45 else "WATCH"
            volume_done.add(pid)
            out.append(_finding(
                "player", pid, "BOX_INVOLVEMENT" if line["box_shots"] >= max(2, line["shots"] // 2) else "ATTACKING_ROLE",
                f"{line['shots']} shot{'s' if line['shots'] != 1 else ''}, {_fmt(line['xg'])} xG ({_pct(share)} of the team's), {goal_part}{assist_part}, {mins_text}; {'; '.join(bits)}",
                (f"{_fmt(per_shot, 3)} xG per shot: {quality}." if line["shots"] > 1 else "A single chance.") + (f" Biggest chance: minute {line['biggest_chance']['minute']} at {_fmt(line['biggest_chance']['xg'])} xG, {line['biggest_chance']['outcome']}." if line["biggest_chance"] else ""),
                direction, "GOAL_THREAT", f"{line['shots']} shots, {_fmt(line['xg'])} xG in {mins_text}", "medium" if line["xg"] >= 0.45 else "low",
                "player shots in match", 0.4 + line["xg"] + (0.2 if line["goals"] else 0),
                metric="player_xg_per90" if line["shots"] >= 3 else None,
            ))
        elif line["dead_ball_shots"] >= 2 and line["dead_ball_shots"] / max(line["shots"], 1) >= 0.6:
            out.append(_finding(
                "player", pid, "SET_PIECE",
                f"{line['dead_ball_shots']} of {line['shots']} shots from set plays ({', '.join(f'{k} {v}' for k, v in line['situations'].items())}), {_fmt(line['xg'])} xG, {pos}, {mins_text}",
                f"{_poss(name)} attempts came from dead balls, the pattern of a target on corners and free kicks.", "WATCH", "SET_PIECES",
                f"{line['dead_ball_shots']} set-piece shots in one match", "low", "player shot situations", 0.35 + line["xg"],
            ))
        elif line["assists"] >= 2 or (line["xa"] or 0) >= 0.5:
            out.append(_finding(
                "player", pid, "CREATION", f"{line['assists']} assist{'s' if line['assists'] != 1 else ''}, {_fmt(line['xa'] or 0)} xA, {mins_text}",
                f"{name} created {_fmt(line['xa'] or 0)} expected assists.", "POSITIVE", "CREATION", f"{_fmt(line['xa'] or 0)} xA", "low", "player_match_state xa", 0.35 + (line["xa"] or 0),
            ))
        if line["on_minute"] is not None and not line["started"] and (line["goals"] or line["xg"] >= 0.3) and pid not in volume_done:
            out.append(_finding(
                "player", pid, "SUBSTITUTION_PATTERN",
                f"Came on at minute {line['on_minute']} and had {line['shots']} shot{'s' if line['shots'] != 1 else ''}, {_fmt(line['xg'])} xG, {line['goals']} goal{'s' if line['goals'] != 1 else ''}",
                f"A bench player with a chance of {_fmt(line['biggest_chance']['xg'] if line['biggest_chance'] else 0)} xG or more in {mins_text}.", "WATCH", "MINUTES",
                f"{_fmt(line['xg'])} xG from the bench in {mins_text}", "low", "player shots, substitution minute", 0.35 + line["xg"] / 2,
            ))
    for chance in sorted([s for s in shots if s["xg"] >= 0.45 and s["outcome"] != "Goal"], key=lambda s: -s["xg"])[:2]:
        pid = chance["player_id"]
        if pid is None:
            continue
        line = next((l for l in lines if l["player_id"] == pid), None)
        out.append(_finding(
            "player", pid, "BOX_INVOLVEMENT", f"Missed a {_fmt(chance['xg'])} xG chance at minute {chance['minute']} ({chance['situation']}, {chance['outcome']})",
            f"{_player_ref(line) if line else chance['player_name']} had the best unconverted chance of {_fmt(chance['xg'])} xG.", "WATCH", "GOAL_THREAT",
            "a big chance missed is variance, the chance itself is the signal", "low", "shot list", 0.35 + chance["xg"] / 2,
        ))
    return out


def _sub_findings(ctx: dict) -> list[dict]:
    out: list[dict] = []
    for sub in ctx["subs"]:
        if sub["kind"] == "INJURY_LINKED" and sub["off_id"] is not None:
            out.append(_finding(
                "player", sub["off_id"], "MINUTES",
                f"Substituted off at minute {sub['minute']} (score margin {sub['margin']:+d}); {sub['note']}",
                "FPL changed his status after this match, so the substitution is read as fitness-related.", "NEGATIVE", "MINUTES",
                "injury-linked substitution after an FPL status change", "high", "match_events substitution + change_events status_change", 0.9,
            ))
    for flag in ctx["status_flags"]:
        if flag["status"] == "s":
            out.append(_finding(
                "player", flag["player_id"], "MINUTES", f"Played {flag['minutes']} minutes; FPL then listed him suspended" + (f": {flag['news']}" if flag.get("news") else ""),
                "He is out for the next fixture(s) FPL names.", "NEGATIVE", "MINUTES", "suspension", "high", "players.status", 0.85,
            ))
    returned = [f for f in ctx["status_flags"] if f["status"] in ("d", "i", "u") and not f["off_minute"] and (f["minutes"] or 0) == 0]
    for flag in returned:
        out.append(_finding(
            "player", flag["player_id"], "MINUTES", f"Did not play; FPL flagged him {flag['label']} after the match" + (f": {flag['news']}" if flag.get("news") else ""),
            "No minutes in this match and a fitness flag raised after it.", "NEGATIVE", "MINUTES", "unavailable with a status change after kickoff", "medium", "change_events status_change", 0.5,
        ))
    injured_by_team: dict[int, list[dict]] = {}
    for sub in ctx["subs"]:
        if sub["kind"] == "INJURY_LINKED":
            injured_by_team.setdefault(sub["team_id"], []).append(sub)
    for tid, rows in injured_by_team.items():
        if len(rows) >= 2:
            names_text = ", ".join(f"{r['off']} (minute {r['minute']})" for r in rows)
            out.append(_finding(
                "team", tid, "TEAM_PATTERN", f"{len(rows)} {ctx['names'][tid]} players came off and were then flagged by FPL: {names_text}",
                "Three or more fitness flags from one match is a squad-availability story, not a set of separate knocks." if len(rows) >= 3 else "Two fitness flags from one match.",
                "NEGATIVE", "MINUTES", f"{len(rows)} injury-linked substitutions", "high", "substitutions + change_events status_change", 0.95,
                short=f"{len(rows)} {ctx['names'][tid]} players subbed off and flagged by FPL",
            ))
    managed = [s for s in ctx["subs"] if s["kind"] == "MANAGED_MINUTES" and s["off_id"] is not None]
    for s in managed[:3]:
        line = next((l for l in ctx["lines"] if l["player_id"] == s["off_id"]), None)
        if not line or not line["started"] or (line["xg"] < 0.2 and not line["goals"]):
            continue
        out.append(_finding(
            "player", s["off_id"], "SUBSTITUTION_PATTERN", f"Withdrawn at minute {s['minute']} with {s['note']}; no FPL fitness flag",
            "A managed-minutes substitution; his minutes were capped by the scoreline, not by form or fitness.", "NEUTRAL", "MINUTES",
            "managed substitution with the game won", "medium", "substitution + score state", 0.4,
        ))
    chasing = [s for s in ctx["subs"] if s["kind"] == "CHASING"]
    by_team: dict[int, list[dict]] = {}
    for s in chasing:
        by_team.setdefault(s["team_id"], []).append(s)
    for tid, rows in by_team.items():
        if len(rows) >= 2:
            minute = min(r["minute"] for r in rows)
            out.append(_finding(
                "team", tid, "TACTICAL_CHANGE", f"{len(rows)} attacking substitutions from minute {minute} while trailing: " + "; ".join(f"{r['on']} for {r['off']} (minute {r['minute']})" for r in rows),
                f"{ctx['names'][tid]} added attackers to chase the game.", "NEUTRAL", "TACTICAL_CHANGE", "chasing changes, not a standing role change", "low", "substitutions", 0.3,
            ))
    return out


def _headline(ctx: dict, findings: list[dict]) -> str:
    m, metrics = ctx["match"], ctx["metrics"]
    base = f"{m['home_name']} {m['home_score']}-{m['away_score']} {m['away_name']}"
    h, a = metrics["home"], metrics["away"]
    parts = [f"{_fmt(h['xg'])} xG to {_fmt(a['xg'])}"] if (h["shots"] or a["shots"]) else []
    seen: set[str] = set()
    for f in findings:
        phrase = f.get("short")
        if phrase and phrase not in seen and f["subject_type"] == "team":
            seen.add(phrase)
            parts.append(phrase)
        if len(parts) >= 3:
            break
    return f"{base}: " + "; ".join(parts) if parts else base


def load_inputs(conn: sqlite3.Connection, match_id: int) -> dict | None:
    m = conn.execute(
        "SELECT mi.id, mi.fotmob_match_id, mi.status, mi.kickoff_utc, mi.home_team_id, mi.away_team_id, mi.home_score, mi.away_score, "
        "th.name AS home_name, ta.name AS away_name FROM match_intelligence mi "
        "JOIN teams th ON th.id = mi.home_team_id JOIN teams ta ON ta.id = mi.away_team_id WHERE mi.id = ?", (match_id,),
    ).fetchone()
    if m is None or m["home_score"] is None or m["away_score"] is None:
        return None
    shots = [
        {"minute": r["minute"], "team_id": r["team_id"], "player_id": r["player_id"], "player_name": r["player_name"], "x": r["x"], "y": r["y"],
         "xg": r["xg"], "xgot": r["xgot"], "on_target": bool(r["is_on_target"]), "outcome": r["outcome"], "situation": r["situation"], "shot_type": r["shot_type"]}
        for r in conn.execute("SELECT * FROM match_shots WHERE match_id = ? ORDER BY minute", (match_id,))
    ]
    events = [
        {"id": r["id"], "minute": r["minute"], "type": r["event_type"], "team_id": r["team_id"], "player_id": r["player_id"], "description": r["description"]}
        for r in conn.execute(
            "SELECT * FROM match_events WHERE match_id = ? AND event_type IN ('Goal','Card','Substitution','VAR','MissedPenalty','AddedTime') "
            "ORDER BY minute, id", (match_id,)
        )
    ]
    pms = [
        {"player_id": r["player_id"], "team_id": r["team_id"], "started": r["started"], "minutes": r["minutes"], "on_min": r["substituted_on_minute"],
         "off_min": r["substituted_off_minute"], "goals": r["goals"], "assists": r["assists"], "xa": r["xa"], "rating": r["rating"]}
        for r in conn.execute("SELECT * FROM player_match_state WHERE match_id = ?", (match_id,))
    ]
    team_ids = (m["home_team_id"], m["away_team_id"])
    players = {
        r["id"]: {"web_name": r["web_name"], "second_name": r["second_name"], "first_name": r["first_name"], "team_id": r["team_id"], "position": _POSITIONS.get(r["element_type"]),
                  "status": r["status"], "news": r["news"], "news_added": r["news_added"]}
        for r in conn.execute(
            "SELECT id, web_name, second_name, first_name, team_id, element_type, status, news, news_added FROM players "
            "WHERE team_id IN (?, ?) OR id IN (SELECT player_id FROM match_events WHERE match_id = ? AND player_id IS NOT NULL)",
            (*team_ids, match_id),
        )
    }
    stray = {e["player_id"] for e in events if e["player_id"] is not None} - set(players)
    for pid in stray:
        r = conn.execute("SELECT id, web_name, second_name, first_name, team_id, element_type, status, news, news_added FROM players WHERE id = ?", (pid,)).fetchone()
        if r:
            players[pid] = {"web_name": r["web_name"], "second_name": r["second_name"], "first_name": r["first_name"], "team_id": r["team_id"], "position": _POSITIONS.get(r["element_type"]),
                            "status": r["status"], "news": r["news"], "news_added": r["news_added"]}
    team_state = {
        r["team_id"]: {"xg": r["xg"], "formation": r["formation"], "possession_pct": r["possession_pct"]}
        for r in conn.execute("SELECT team_id, xg, formation, possession_pct FROM team_match_state WHERE match_id = ?", (match_id,))
    }
    team_state_xg = {tid: v["xg"] for tid, v in team_state.items()}
    status_after = _status_changes_after(conn, m["kickoff_utc"], [p["player_id"] for p in pms if p["player_id"] is not None])
    return {
        "status_after": status_after, "team_state_xg": team_state_xg, "team_state": team_state,
        "match": {"id": m["id"], "fotmob_match_id": m["fotmob_match_id"], "status": m["status"], "kickoff": m["kickoff_utc"],
                  "home_id": m["home_team_id"], "away_id": m["away_team_id"], "home_name": m["home_name"], "away_name": m["away_name"],
                  "home_score": m["home_score"], "away_score": m["away_score"]},
        "shots": shots, "events": events, "pms": pms, "players": players,
    }


STATUS_WINDOW_HOURS = 48


def _status_changes_after(conn: sqlite3.Connection, kickoff: str | None, player_ids: list[int]) -> dict[int, dict]:
    """A player's first move to a non-available FPL status within 48 hours of kickoff, from the change log."""
    if not kickoff or not player_ids:
        return {}
    try:
        t0 = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
    except ValueError:
        return {}
    t1 = t0.timestamp() + STATUS_WINDOW_HOURS * 3600
    marks = ",".join("?" * len(player_ids))
    out: dict[int, dict] = {}
    rows = conn.execute(
        f"SELECT entity_id, new_value, detected_at FROM change_events WHERE event_type = 'status_change' AND entity = 'player' "
        f"AND entity_id IN ({marks}) AND detected_at >= ? ORDER BY detected_at", (*player_ids, t0.isoformat()),
    ).fetchall()
    for r in rows:
        try:
            seen = datetime.fromisoformat(r["detected_at"]).timestamp()
        except ValueError:
            continue
        if seen > t1 or r["new_value"] not in _NEWS_STATUSES or r["entity_id"] in out:
            continue
        out[r["entity_id"]] = {"status": r["new_value"], "detected_at": r["detected_at"], "news": None}
    if out:
        marks2 = ",".join("?" * len(out))
        for r in conn.execute(f"SELECT id, news, news_added FROM players WHERE id IN ({marks2})", tuple(out)):
            added = r["news_added"]
            if r["news"] and added:
                try:
                    when = datetime.fromisoformat(added.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    continue
                if t0.timestamp() <= when <= t1:
                    out[r["id"]]["news"] = r["news"]
    return out


_LEAGUE_CACHE: dict[tuple, dict] = {}


def cached_league_profile(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT COUNT(*) AS n, COALESCE(MAX(retrieved_at), '') AS t FROM match_shots").fetchone()
    key = (str(conn.execute("PRAGMA database_list").fetchone()[2]), row["n"], row["t"])
    if key not in _LEAGUE_CACHE:
        _LEAGUE_CACHE.clear()
        _LEAGUE_CACHE[key] = league_profile(conn)
    return _LEAGUE_CACHE[key]


def analyse_match(conn: sqlite3.Connection, match_id: int, rel: dict | None = None) -> dict | None:
    from fpl_agent.models.signal_reliability import annotate_story, reliability

    inputs = load_inputs(conn, match_id)
    if inputs is None or inputs["match"]["status"] != "FULL_TIME":
        return None
    story = build_story(inputs, cached_league_profile(conn))
    return annotate_story(story, rel if rel is not None else reliability(conn))


def store_story(conn: sqlite3.Connection, story: dict) -> None:
    conn.execute(
        "INSERT INTO match_story (match_id, engine_version, story_json, generated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(match_id) DO UPDATE SET engine_version = excluded.engine_version, story_json = excluded.story_json, generated_at = excluded.generated_at",
        (story["match_id"], story["version"], json.dumps(story, separators=(",", ":")), datetime.now(timezone.utc).isoformat()),
    )


def load_story(conn: sqlite3.Connection, match_id: int) -> dict | None:
    row = conn.execute("SELECT story_json FROM match_story WHERE match_id = ?", (match_id,)).fetchone()
    return json.loads(row["story_json"]) if row else None


def refresh_stories(conn: sqlite3.Connection, force: bool = False) -> int:
    """Build or rebuild the story of every FULL_TIME match whose stored story is missing, from an older engine, or older than its shots."""
    rows = conn.execute(
        "SELECT mi.id FROM match_intelligence mi LEFT JOIN match_story ms ON ms.match_id = mi.id WHERE mi.status = 'FULL_TIME' "
        "AND (? = 1 OR ms.match_id IS NULL OR ms.engine_version != ? OR ms.generated_at < COALESCE((SELECT MAX(retrieved_at) FROM match_shots s WHERE s.match_id = mi.id), ''))",
        (1 if force else 0, ENGINE_VERSION),
    ).fetchall()
    from fpl_agent.models.signal_reliability import annotate_story, reliability

    built = 0
    for r in rows:
        story = analyse_match(conn, r["id"], rel={"metrics": {}})
        if story is not None:
            store_story(conn, story)
            built += 1
    conn.commit()
    if built or force:
        rel = reliability(conn)
        for r in conn.execute("SELECT match_id FROM match_story").fetchall():
            story = load_story(conn, r["match_id"])
            store_story(conn, annotate_story(story, rel))
        conn.commit()
    return built


def _team_state_row(story: dict, side: str) -> dict:
    m = story["metrics"][side]
    tid = story["match"][side]["team_id"]
    name = story["match"][side]["name"]
    ts = (story.get("team_state") or {}).get(str(tid)) or {}
    mine = [f for f in story["findings"] if f["subject_type"] == "team" and f["subject_id"] == tid]
    formation = ts.get("formation")
    possession = ts.get("possession_pct")
    tactical = ", ".join(x for x in (formation, f"{round(possession)}% possession" if possession is not None else None) if x) or "formation not recorded"
    attack = f"{m['shots']} shots, {m['xg']:.2f} xG, {m['goals']} goals"
    if m["dead_ball_xg_share"] is not None and m["dead_ball_shots"] >= 3:
        attack += f"; {round(100 * m['dead_ball_xg_share'])}% of xG from dead balls"
    defence = f"{m['shots_against']} shots against, {m['xg_against']:.2f} xG, {m['goals_conceded_excl_og']} conceded"
    lead = mine[0] if mine else None
    return {
        "team_id": tid, "tactical_signal": tactical, "attacking_signal": attack, "defensive_signal": defence,
        "key_observation": (lead["short"] or lead["observed"]) if lead else f"{name}: no finding cleared the thresholds",
        "fpl_implication": (lead["fpl_reason"] or "no FPL implication measured") if lead else "no FPL implication measured",
        "confidence": "medium" if lead and lead["confidence"] != "low" else "low", "evidence_ref": "match_analyst team metrics",
    }


def _player_state_rows(story: dict) -> list[dict]:
    rows = []
    seen: set[int] = set()
    by_player: dict[int, list[dict]] = {}
    for f in story["findings"]:
        if f["subject_type"] == "player":
            by_player.setdefault(f["subject_id"], []).append(f)
    for line in story["players"]:
        pid = line["player_id"]
        if pid in seen or pid not in by_player:
            continue
        if line["xg"] < 0.3 and not line["goals"] and not any(f["fpl_direction"] == "NEGATIVE" for f in by_player[pid]):
            continue
        seen.add(pid)
        top = by_player[pid][0]
        minutes = f"{line['minutes']} minutes" if line["minutes"] is not None else "minutes unknown"
        rows.append({
            "player_id": pid, "role": f"{line.get('position') or '?'}, {'started' if line['started'] else 'substitute'}, {minutes}",
            "tactical_signal": top["observed"], "fpl_outlook": top["fpl_reason"] or top["inferred"] or "see the finding",
            "confidence": top["confidence"], "evidence_ref": top["evidence_ref"],
        })
    for pid, fs in by_player.items():
        if pid in seen:
            continue
        top = next((f for f in fs if f["fpl_direction"] == "NEGATIVE"), None)
        if top is not None:
            rows.append({"player_id": pid, "role": "see finding", "tactical_signal": top["observed"], "fpl_outlook": top["fpl_reason"] or "see the finding",
                         "confidence": top["confidence"], "evidence_ref": top["evidence_ref"]})
    return rows[:10]


def draft_payload(story: dict, max_findings: int = 14) -> dict:
    """The story as a `match-analyze` payload. `rank`, `short`, `metric` and `name` are dropped; the schema never saw them."""
    from fpl_agent.models.signal_reliability import reliability_sentence

    observations = []
    for f in story["findings"][:max_findings]:
        o = {k: v for k, v in f.items() if k not in ("rank", "short", "metric", "reliability", "name")}
        sentence = reliability_sentence(f)
        if sentence and o.get("inferred"):
            o["inferred"] = f"{o['inferred']} {sentence}"
        observations.append(o)
    return {
        "headline": story["headline"], "uncertainties": story["uncertainties"], "observations": observations,
        "player_states": _player_state_rows(story), "team_states": [_team_state_row(story, "home"), _team_state_row(story, "away")],
    }
