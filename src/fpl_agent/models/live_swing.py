"""WHO TO CHEER: what each match still in play or to come is worth against the top 10k, and who has moved you so far.

A player's stake is your multiplier minus the field's effective ownership (`rank_engine.build_field`, top 10k): a point he
scores moves you against the field by that much. The edge so far is the sum of stake x live points over every player.

Your multipliers follow FPL's rules as matches end: a starter on 0 minutes whose match is over gives way to the bench and the
vice takes a dead armband (`gw_review.autosub_watch`). Live points add the provisional bonus of any match FPL has not yet
confirmed (`live_bonus.compute_live_bonus`).

A next goal for a side is the shares-weighted stake of its players on the pitch at FPL's scoring values with the bonus a
goal or assist carries, plus the assist on 0.9 of goals, less what the other side's clean-sheet holders lose: the sheet and
its bonus while it stands, and the point a keeper or defender drops on every second goal. A holder is anyone who has played
60 minutes, on the pitch or not, or is on it and can still reach 60. A side is the one to cheer when its next goal beats the
other's by `CHEER_BAND`.

Assumptions: goal and assist shares come from the frozen projections' goals and assists parts (position weights when a
gameweek has none); one player's share is rescaled over those on the pitch, so a sub on is counted at his projected share;
before kickoff a holder counts at his projected chance of 60 minutes; bonus per goal, assist and clean sheet is the GW1-8
fit (2026-10-29), not this match's BPS table; a double gameweek's minutes are the gameweek's. The field's multipliers are
its picks as locked, without its own substitutions, and its ownership is a sample of 750."""
import json
import sqlite3

GOAL_POINTS = {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4}
CLEAN_SHEET_POINTS = {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}
ASSIST_POINTS = 3
ASSISTED_RATE = 0.9
BONUS_PER_GOAL = 1.4
BONUS_PER_ASSIST = 0.4
CLEAN_SHEET_BONUS = {"GKP": 1.0, "DEF": 0.5, "MID": 0.0, "FWD": 0.0}
CONCEDES_POINT = ("GKP", "DEF")
CLEAN_SHEET_MINUTES = 60
FULL_MATCH = 90
CHEER_BAND = 0.5
MOVERS = 6
_FALLBACK_GOALS = {"GKP": 0.0, "DEF": 0.3, "MID": 1.0, "FWD": 2.0}
_FALLBACK_ASSISTS = {"GKP": 0.05, "DEF": 0.4, "MID": 1.0, "FWD": 0.7}


def side_next_goal(players: list[dict], holders: list[dict], enemy_goals_against: int = 0) -> float:
    """`players` are a side's men on the pitch: position, stake, goals and assists weights. `holders` are the other side's
    clean-sheet holders (position, stake, `cs` weight) and `enemy_goals_against` what that side has conceded so far."""
    goals = sum(p["goals"] for p in players)
    assists = sum(p["assists"] for p in players)
    value = 0.0
    if goals > 0:
        value += sum(p["goals"] / goals * (GOAL_POINTS[p["position"]] + BONUS_PER_GOAL) * p["stake"] for p in players)
    if assists > 0:
        value += ASSISTED_RATE * sum(p["assists"] / assists * (ASSIST_POINTS + BONUS_PER_ASSIST) * p["stake"] for p in players)
    if enemy_goals_against == 0:
        value -= sum((CLEAN_SHEET_POINTS[p["position"]] + CLEAN_SHEET_BONUS[p["position"]]) * p["stake"] * p["cs"] for p in holders)
    if (enemy_goals_against + 1) % 2 == 0:
        value -= sum(p["stake"] * p["cs"] for p in holders if p["position"] in CONCEDES_POINT)
    return value


def clean_sheet_holder(minutes: int, on_pitch: bool, match_minute: float, sent_off: bool = False) -> bool:
    if minutes >= CLEAN_SHEET_MINUTES:
        return True
    return on_pitch and not sent_off and minutes + max(FULL_MATCH - match_minute, 0) >= CLEAN_SHEET_MINUTES


def effective_multipliers(picks: list[dict], minutes: dict[int, int], team_done: dict[int, bool]) -> tuple[dict[int, int], list[tuple[int, int]]]:
    """`picks` in squad order: player_id, multiplier, is_vice, position, team_id. FPL's substitutions and armband as they stand."""
    from fpl_agent.models.gw_review import autosub_watch

    mine = {p["player_id"]: p["multiplier"] for p in picks}
    squad = [{"player_id": p["player_id"], "starting": p["multiplier"] > 0, "position": p["position"]} for p in picks]
    done = {p["player_id"]: team_done.get(p["team_id"], True) for p in picks}
    made = [w for w in autosub_watch(squad, minutes, done) if w["status"] == "made"]
    subs = []
    for w in made:
        mine[w["out"]] = 0
        if w["into"] is not None:
            mine[w["into"]] = 1
            subs.append((w["out"], w["into"]))
    captain = next((p for p in picks if p["multiplier"] > 1), None)
    vice = next((p for p in picks if p["is_vice"]), None)
    if captain and vice and mine[captain["player_id"]] == 0 and mine[vice["player_id"]] == 1:
        mine[vice["player_id"]] = captain["multiplier"]
    return mine, subs


def cheer_for(home: float, away: float) -> str | None:
    if abs(home - away) < CHEER_BAND:
        return None
    return "home" if home > away else "away"


def _squads(conn: sqlite3.Connection, event: int, team_ids: set[int], mine: dict[int, int], eo: dict[int, float]) -> dict[int, list[dict]]:
    marks = ",".join("?" * len(team_ids))
    parts = {r["player_id"]: json.loads(r["predicted_components"]) for r in conn.execute(
        "SELECT player_id, predicted_components FROM prediction_outcomes WHERE event = ? AND predicted_components IS NOT NULL", (event,))}
    out: dict[int, list[dict]] = {t: [] for t in team_ids}
    fallback = not parts
    for r in conn.execute(
        f"SELECT p.id, p.web_name, p.code, p.team_id, t.code AS team_code, et.singular_name_short AS position FROM players p "
        f"JOIN teams t ON t.id = p.team_id JOIN element_types et ON et.id = p.element_type WHERE p.team_id IN ({marks}) AND p.removed = 0",
        sorted(team_ids),
    ):
        part = parts.get(r["id"], {})
        out[r["team_id"]].append({
            "player_id": r["id"], "name": r["web_name"], "photo_code": r["code"], "team_code": r["team_code"], "position": r["position"],
            "stake": mine.get(r["id"], 0) - eo.get(r["id"], 0.0),
            "goals": _FALLBACK_GOALS[r["position"]] if fallback else part.get("goals", 0.0),
            "assists": _FALLBACK_ASSISTS[r["position"]] if fallback else part.get("assists", 0.0),
            "cs": 1.0 if fallback else part.get("p_full", 0.0),
        })
    return out


def _in_match(conn: sqlite3.Connection, state, players: list[dict], stats: dict[int, dict]) -> tuple[list[dict], list[dict]]:
    """The side's men on the pitch, and its clean-sheet holders."""
    from fpl_agent.models.live_forecast import _on_pitch

    if state.status == "pre":
        return players, players
    field, holders = [], []
    for p in players:
        s = stats.get(p["player_id"], {})
        played = s.get("minutes", 0)
        off = bool(s.get("red_cards"))
        on = not off and _on_pitch(conn, state.fixture_id, p["player_id"], played, state.minute)
        if on:
            field.append(p)
        if clean_sheet_holder(played, on, state.minute, off):
            holders.append({**p, "cs": 1.0})
    return field, holders


def swing(conn: sqlite3.Connection, event: int, picks: list[dict], stats: dict[int, dict], eo: dict[int, float], states: list, pending_bonus: dict[int, int] | None = None) -> dict:
    minutes = {pid: s.get("minutes", 0) for pid, s in stats.items()}
    team_done: dict[int, bool] = {}
    for s in states:
        for team in (s.home_id, s.away_id):
            team_done[team] = team_done.get(team, True) and s.status == "done"
    mine, subs = effective_multipliers(picks, minutes, team_done)
    points = {pid: s.get("total_points", 0) + (pending_bonus or {}).get(pid, 0) for pid, s in stats.items()}
    edge = sum((mine.get(pid, 0) - eo.get(pid, 0.0)) * pts for pid, pts in points.items())
    players = {r["id"]: r for r in conn.execute(
        "SELECT p.id, p.web_name, p.code, t.short_name, t.code AS team_code FROM players p JOIN teams t ON t.id = p.team_id")}
    movers = []
    for pid, pts in points.items():
        stake = mine.get(pid, 0) - eo.get(pid, 0.0)
        if pts and abs(stake * pts) >= 0.05 and pid in players:
            p = players[pid]
            movers.append({"player_id": pid, "name": p["web_name"], "photo_code": p["code"], "team_code": p["team_code"], "team_short": p["short_name"],
                           "points": pts, "mine": mine.get(pid, 0), "eo": round(eo.get(pid, 0.0), 2), "edge": round(stake * pts, 1)})
    movers.sort(key=lambda m: -m["edge"])
    left = [s for s in states if s.status != "done"]
    teams = {t for s in left for t in (s.home_id, s.away_id)}
    squads = _squads(conn, event, teams, mine, eo) if teams else {}
    shorts = {r["id"]: r for r in conn.execute("SELECT id, short_name, code FROM teams")}
    cards = []
    for s in sorted(left, key=lambda x: (x.status != "live", x.kickoff or "")):
        (home, home_holders), (away, away_holders) = _in_match(conn, s, squads[s.home_id], stats), _in_match(conn, s, squads[s.away_id], stats)
        next_home = side_next_goal(home, away_holders, s.home_goals)
        next_away = side_next_goal(away, home_holders, s.away_goals)
        side = lambda team, goals, nxt: {"short": shorts[team]["short_name"], "code": shorts[team]["code"], "goals": goals, "next_goal": round(nxt, 1)}
        at_stake = sorted((p for p in home + away if abs(p["stake"]) >= 0.05), key=lambda p: -abs(p["stake"]))[:3]
        cards.append({
            "fixture": s.fixture_id, "status": s.status, "minute": round(s.minute), "kickoff": s.kickoff,
            "home": side(s.home_id, s.home_goals, next_home), "away": side(s.away_id, s.away_goals, next_away),
            "cheer": cheer_for(next_home, next_away),
            "key": [{k: p[k] for k in ("player_id", "name", "photo_code", "team_code")} | {"stake": round(p["stake"], 2)} for p in at_stake],
        })
    return {
        "status": "ok", "event": event, "edge": round(edge, 1), "matches": cards, "subs": len(subs), "bonus_pending": sum((pending_bonus or {}).values()),
        "helping": [m for m in movers if m["edge"] > 0][:MOVERS], "hurting": [m for m in reversed(movers) if m["edge"] < 0][:MOVERS],
    }
