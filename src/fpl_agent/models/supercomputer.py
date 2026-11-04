"""THE SUPERCOMPUTER: the rest of the Premier League season played `SIMULATIONS` times from the project's Dixon-Coles ratings.

Every unplayed fixture is drawn as two Poisson scores from the ratings' expected goals. Each simulated season first gives
every club a lasting shock to its attack and defence (log-normal, `STRENGTH_SD`), so a club's luck persists through a season
as ratings really drift; without it the simulation is sure of itself far too early. `STRENGTH_SD` is chosen by `backtest`:
each stored season restarted after 90 matches and set against how it finished (2021-22 to 2025-26, 2026-11-04). Title, top
four and relegation Brier summed over clubs: 3.62 at 0, 3.53 at 0.10, 3.45 at 0.20, 3.45 at 0.25; final points off by 7.9 a
club at every value. The title alone scored best at 0 (0.39 against 0.43 at 0.20) on five title races, a thin sample.

The Golden Boot adds each player's share of his club's simulated goals to his total so far. Shares come from the latest
frozen projections' goals part, so they hold a player's current role and availability for the rest of the season.

Assumptions: scores are independent Poisson, leaving out the Dixon-Coles low-score correction; ties break on goal difference,
goals scored, then at random; no injuries, managers or transfers beyond the shock; ratings are as of the cutoff with no odds
blended, unlike the projections' next fixtures; a club with no stored history falls back on league-average ratings."""
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import numpy as np

SIMULATIONS = 20000
HISTORY_SIMULATIONS = 4000
STRENGTH_SD = 0.20
TOP_FOUR = 4
TOP_FIVE = 5
RELEGATED = 3
RACE_SIZE = 30
RACE_SHOWN = 8
RUN_SHOWN = 6
GOAL_POINTS = {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4}
FALLBACK_GOALS = 1.35


@dataclass
class League:
    teams: list[int]
    points: np.ndarray
    gd: np.ndarray
    gf: np.ndarray
    home: np.ndarray
    away: np.ndarray
    lam: np.ndarray
    mu: np.ndarray


def simulate_table(league: League, sims: int, strength_sd: float, seed: int = 26) -> dict:
    """Returns position counts [team, position], final points [sim, team] and each club's goals to come [sim, team]."""
    rng = np.random.default_rng(seed)
    n, m = len(league.teams), len(league.home)
    attack = rng.normal(0.0, strength_sd, (sims, n)) if strength_sd else np.zeros((sims, n))
    defence = rng.normal(0.0, strength_sd, (sims, n)) if strength_sd else np.zeros((sims, n))
    points = np.tile(league.points, (sims, 1)).astype(float)
    gd = np.tile(league.gd, (sims, 1)).astype(float)
    gf = np.tile(league.gf, (sims, 1)).astype(float)
    goals_left = np.zeros((sims, n))
    if m:
        lam = league.lam * np.exp(attack[:, league.home] + defence[:, league.away])
        mu = league.mu * np.exp(attack[:, league.away] + defence[:, league.home])
        hg, ag = rng.poisson(lam), rng.poisson(mu)
        rows = np.arange(sims)[:, None]
        np.add.at(points, (rows, league.home), 3 * (hg > ag) + (hg == ag))
        np.add.at(points, (rows, league.away), 3 * (ag > hg) + (hg == ag))
        np.add.at(gd, (rows, league.home), hg - ag)
        np.add.at(gd, (rows, league.away), ag - hg)
        np.add.at(goals_left, (rows, league.home), hg)
        np.add.at(goals_left, (rows, league.away), ag)
        gf += goals_left
    order = points * 1e6 + gd * 1e3 + gf + rng.random(points.shape)
    position = np.argsort(np.argsort(-order, axis=1), axis=1)
    counts = np.stack([(position == p).sum(axis=0) for p in range(n)], axis=1)
    return {"counts": counts, "points": points, "goals_left": goals_left}


def _fpl_ratings(conn: sqlite3.Connection, as_of: str):
    from fpl_agent.models.expected_points import _fit_dc_model

    model = _fit_dc_model(conn, as_of)
    ids = {r["fpl_team_id"]: r["id"] for r in conn.execute("SELECT id, fpl_team_id FROM market_teams WHERE fpl_team_id IS NOT NULL")}
    return model, ids


def _goals(model, ids: dict, home: int, away: int) -> tuple[float, float]:
    from fpl_agent.models.team_strength_dc import expected_goals

    h, a = ids.get(home), ids.get(away)
    if model is None or h not in model.teams or a not in model.teams:
        return FALLBACK_GOALS, FALLBACK_GOALS
    return expected_goals(model, h, a)


def league_state(conn: sqlite3.Connection, through_event: int | None = None) -> tuple[League, list[dict], str]:
    rows = conn.execute("SELECT id, event, kickoff_time, team_h, team_a, team_h_score, team_a_score FROM fixtures ORDER BY kickoff_time").fetchall()
    teams = sorted({r["team_h"] for r in rows} | {r["team_a"] for r in rows})
    at = {t: i for i, t in enumerate(teams)}
    played = [r for r in rows if r["team_h_score"] is not None and (through_event is None or (r["event"] or 99) <= through_event)]
    gone = {r["id"] for r in played}
    left = [r for r in rows if r["id"] not in gone]
    as_of = next((r["kickoff_time"][:10] for r in left if r["kickoff_time"]), date.today().isoformat())
    model, ids = _fpl_ratings(conn, as_of)
    n = len(teams)
    points, gd, gf = np.zeros(n), np.zeros(n), np.zeros(n)
    for r in played:
        h, a, hg, ag = at[r["team_h"]], at[r["team_a"]], r["team_h_score"], r["team_a_score"]
        points[h] += 3 if hg > ag else 1 if hg == ag else 0
        points[a] += 3 if ag > hg else 1 if hg == ag else 0
        gd[h] += hg - ag
        gd[a] += ag - hg
        gf[h] += hg
        gf[a] += ag
    pairs = [_goals(model, ids, r["team_h"], r["team_a"]) for r in left]
    league = League(
        teams, points, gd, gf, np.array([at[r["team_h"]] for r in left], dtype=int), np.array([at[r["team_a"]] for r in left], dtype=int),
        np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs]),
    )
    return league, [dict(r) for r in left], as_of


def _odds(result: dict, sims: int) -> dict[str, np.ndarray]:
    c = result["counts"]
    n = c.shape[0]
    return {
        "title": c[:, 0] / sims, "top4": c[:, :TOP_FOUR].sum(axis=1) / sims, "top5": c[:, :TOP_FIVE].sum(axis=1) / sims,
        "down": c[:, n - RELEGATED:].sum(axis=1) / sims,
    }


def goal_race(conn: sqlite3.Connection, league: League, goals_left: np.ndarray, seed: int = 27) -> list[dict]:
    from fpl_agent.models.rules import current_season

    season = current_season(conn)
    so_far = {r["player_id"]: r["g"] or 0 for r in conn.execute("SELECT player_id, SUM(goals) AS g FROM player_gw_stats WHERE season = ? GROUP BY player_id", (season,))}
    event = conn.execute("SELECT MAX(event) AS e FROM prediction_outcomes WHERE predicted_components IS NOT NULL").fetchone()["e"]
    if event is None:
        return []
    at = {t: i for i, t in enumerate(league.teams)}
    rows = conn.execute(
        "SELECT o.player_id, o.predicted_components AS c, p.web_name, p.code, p.team_id, t.code AS team_code, t.short_name, et.singular_name_short AS position "
        "FROM prediction_outcomes o JOIN players p ON p.id = o.player_id JOIN teams t ON t.id = p.team_id JOIN element_types et ON et.id = p.element_type "
        "WHERE o.event = ? AND o.predicted_components IS NOT NULL", (event,),
    ).fetchall()
    rate = {r["player_id"]: json.loads(r["c"]).get("goals", 0.0) / GOAL_POINTS[r["position"]] for r in rows}
    team_rate: dict[int, float] = {}
    for r in rows:
        team_rate[r["team_id"]] = team_rate.get(r["team_id"], 0.0) + rate[r["player_id"]]
    mean_left = goals_left.mean(axis=0)
    shown = []
    for r in rows:
        share = rate[r["player_id"]] / team_rate[r["team_id"]] if team_rate[r["team_id"]] else 0.0
        shown.append((so_far.get(r["player_id"], 0) + share * mean_left[at[r["team_id"]]], share, r))
    shown.sort(key=lambda x: -x[0])
    field = shown[:RACE_SIZE]
    rng = np.random.default_rng(seed)
    totals = np.stack([so_far.get(r["player_id"], 0) + rng.binomial(goals_left[:, at[r["team_id"]]].astype(int), share) for _, share, r in field], axis=1)
    top = totals.max(axis=1, keepdims=True)
    winners = totals == top
    wins = (winners / winners.sum(axis=1, keepdims=True)).mean(axis=0)
    out = [{
        "player_id": r["player_id"], "name": r["web_name"], "photo_code": r["code"], "team_code": r["team_code"], "team_short": r["short_name"],
        "goals": so_far.get(r["player_id"], 0), "expected_final": round(float(totals[:, i].mean()), 1), "chance": round(float(wins[i]), 3),
    } for i, (_, _, r) in enumerate(field)]
    return sorted(out, key=lambda x: -x["chance"])[:RACE_SHOWN]


def _club_runs(league: League, left: list[dict], next_event: int | None) -> dict[int, dict]:
    """Expected goals and clean sheets for each club over the rest of the season and its next six gameweeks."""
    n = len(league.teams)
    goals, sheets, soon_goals, soon_sheets = [np.zeros(n) for _ in range(4)]
    for k, f in enumerate(left):
        h, a, lam, mu = league.home[k], league.away[k], league.lam[k], league.mu[k]
        goals[h] += lam
        goals[a] += mu
        sheets[h] += math.exp(-mu)
        sheets[a] += math.exp(-lam)
        if next_event is not None and f["event"] is not None and f["event"] < next_event + RUN_SHOWN:
            soon_goals[h] += lam
            soon_goals[a] += mu
            soon_sheets[h] += math.exp(-mu)
            soon_sheets[a] += math.exp(-lam)
    return {t: {"goals_left": round(goals[i], 1), "sheets_left": round(sheets[i], 1), "goals_next": round(soon_goals[i], 1), "sheets_next": round(soon_sheets[i], 1)}
            for i, t in enumerate(league.teams)}


def _river(conn: sqlite3.Connection, last_played: int) -> list[dict]:
    """The title and relegation race as it stood after each finished gameweek, from the data of that moment."""
    out = []
    for event in range(1, last_played + 1):
        league, _, _ = league_state(conn, through_event=event)
        result = simulate_table(league, HISTORY_SIMULATIONS, STRENGTH_SD, seed=100 + event)
        odds = _odds(result, HISTORY_SIMULATIONS)
        out.append({"event": event, "title": {t: round(float(odds["title"][i]), 3) for i, t in enumerate(league.teams)},
                    "down": {t: round(float(odds["down"][i]), 3) for i, t in enumerate(league.teams)}})
    return out


def run(conn: sqlite3.Connection, sims: int = SIMULATIONS) -> dict:
    league, left, as_of = league_state(conn)
    result = simulate_table(league, sims, STRENGTH_SD)
    odds = _odds(result, sims)
    info = {r["id"]: r for r in conn.execute("SELECT id, name, short_name, code FROM teams")}
    played = conn.execute("SELECT team, COUNT(*) AS n FROM (SELECT team_h AS team FROM fixtures WHERE team_h_score IS NOT NULL UNION ALL SELECT team_a FROM fixtures WHERE team_a_score IS NOT NULL) GROUP BY team").fetchall()
    games = {r["team"]: r["n"] for r in played}
    last = conn.execute("SELECT MAX(event) AS e FROM fixtures WHERE team_h_score IS NOT NULL").fetchone()["e"] or 0
    next_event = min((f["event"] for f in left if f["event"] is not None), default=None)
    runs = _club_runs(league, left, next_event)
    rows = []
    pts = result["points"]
    for i, t in enumerate(league.teams):
        rows.append({
            "team_id": t, "name": info[t]["name"], "short": info[t]["short_name"], "code": info[t]["code"], "played": games.get(t, 0), "points": int(league.points[i]),
            "gd": int(league.gd[i]), "expected_points": round(float(pts[:, i].mean()), 1), "p10": int(np.percentile(pts[:, i], 10)), "p90": int(np.percentile(pts[:, i], 90)),
            "title": round(float(odds["title"][i]), 4), "top4": round(float(odds["top4"][i]), 4), "top5": round(float(odds["top5"][i]), 4), "down": round(float(odds["down"][i]), 4),
            "positions": [round(float(x), 4) for x in result["counts"][i] / sims], **runs[t],
        })
    rows.sort(key=lambda r: -r["expected_points"])
    return {
        "status": "ok", "generated_at": datetime.now(timezone.utc).isoformat(), "as_of": as_of, "simulations": sims, "fixtures_left": len(left),
        "strength_sd": STRENGTH_SD, "last_gameweek": last, "next_gameweek": next_event, "table": rows,
        "golden_boot": goal_race(conn, league, result["goals_left"]), "river": _river(conn, last),
    }


def backtest(conn: sqlite3.Connection, seasons: tuple[str, ...], sds: tuple[float, ...], after_matches: int = 90, sims: int = 4000) -> dict:
    """Each season restarted after `after_matches`, on ratings as of that date, against how it finished."""
    from fpl_agent.models.team_strength_dc import fit_dixon_coles, load_matches_for_fitting

    frames = []
    for season in seasons:
        rows = conn.execute("SELECT match_date, home_team_id AS h, away_team_id AS a, home_goals AS hg, away_goals AS ag FROM match_results_history WHERE season = ? ORDER BY match_date", (season,)).fetchall()
        if len(rows) < 380:
            continue
        teams = sorted({r["h"] for r in rows} | {r["a"] for r in rows})
        at = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        final_pts, final_gd, final_gf = np.zeros(n), np.zeros(n), np.zeros(n)
        pts, gd, gf = np.zeros(n), np.zeros(n), np.zeros(n)
        for k, r in enumerate(rows):
            h, a = at[r["h"]], at[r["a"]]
            for arr_p, arr_d, arr_f in ([final_pts, final_gd, final_gf], [pts, gd, gf]) if k < after_matches else ([final_pts, final_gd, final_gf],):
                arr_p[h] += 3 if r["hg"] > r["ag"] else 1 if r["hg"] == r["ag"] else 0
                arr_p[a] += 3 if r["ag"] > r["hg"] else 1 if r["hg"] == r["ag"] else 0
                arr_d[h] += r["hg"] - r["ag"]
                arr_d[a] += r["ag"] - r["hg"]
                arr_f[h] += r["hg"]
                arr_f[a] += r["ag"]
        cutoff = rows[after_matches]["match_date"]
        matches, ids = load_matches_for_fitting(conn, (date.fromisoformat(cutoff[:10]) + timedelta(days=0)).isoformat())
        model = fit_dixon_coles(matches, ids)
        from fpl_agent.models.team_strength_dc import expected_goals

        left = rows[after_matches:]
        goals = [expected_goals(model, r["h"], r["a"]) for r in left]
        league = League(teams, pts, gd, gf, np.array([at[r["h"]] for r in left]), np.array([at[r["a"]] for r in left]), np.array([g[0] for g in goals]), np.array([g[1] for g in goals]))
        order = np.argsort(np.argsort(-(final_pts * 1e6 + final_gd * 1e3 + final_gf)))
        frames.append((season, league, final_pts, order))
    out = {}
    for sd in sds:
        title = top4 = down = 0.0
        err, count = 0.0, 0
        for _, league, final_pts, order in frames:
            result = simulate_table(league, sims, sd)
            odds = _odds(result, sims)
            title += float(((odds["title"] - (order == 0)) ** 2).sum())
            top4 += float(((odds["top4"] - (order < TOP_FOUR)) ** 2).sum())
            down += float(((odds["down"] - (order >= 17)) ** 2).sum())
            err += float(np.abs(result["points"].mean(axis=0) - final_pts).sum())
            count += len(final_pts)
        out[sd] = {"title_brier": round(title / len(frames), 3), "top4_brier": round(top4 / len(frames), 3), "down_brier": round(down / len(frames), 3), "points_mae": round(err / count, 2)}
    return {"seasons": [f[0] for f in frames], "by_sd": out}
