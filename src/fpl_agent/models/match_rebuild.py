"""A finished match rebuilt from its shots.

Every shot carries the chance it was worth (xG). Treating the shots as
independent, the number of goals each side deserved is a Poisson-binomial
distribution; convolving the two gives the probability that the match, replayed
from the same chances, would end as a home win, a draw or an away win. That
turns "City won 3-0 from 1.3 xG" into a number: how often a side with those
chances wins at all.

Assumptions: shots are independent (a rebound and its first shot are not
linked), the xG model is the source's own, and own goals have no shot attached so
they appear only in the final score. The timeline is cumulative xG against the
minute of each shot, which is what a manager can read: when the match tilted,
and whether the goals followed the chances or ran ahead of them."""
import sqlite3

import numpy as np

_MAX_GOALS = 12


def goal_distribution(xgs: list[float]) -> np.ndarray:
    """P(exactly k goals) for k = 0.._MAX_GOALS, shots independent."""
    dist = np.zeros(_MAX_GOALS + 1)
    dist[0] = 1.0
    for p in xgs:
        p = min(max(p, 0.0), 1.0)
        shifted = np.concatenate(([0.0], dist[:-1]))
        dist = dist * (1 - p) + shifted * p
    return dist


def deserved_result(home_xgs: list[float], away_xgs: list[float]) -> dict:
    hd, ad = goal_distribution(home_xgs), goal_distribution(away_xgs)
    joint = np.outer(hd, ad)
    home_win = float(np.tril(joint, -1).sum())
    away_win = float(np.triu(joint, 1).sum())
    draw = float(np.trace(joint))
    best = np.unravel_index(int(np.argmax(joint)), joint.shape)
    return {
        "home_win": home_win, "draw": draw, "away_win": away_win,
        "home_points": 3 * home_win + draw, "away_points": 3 * away_win + draw,
        "likely_score": [int(best[0]), int(best[1])],
    }


def rebuild_match(conn: sqlite3.Connection, match_id: int) -> dict | None:
    m = conn.execute(
        "SELECT mi.id, mi.kickoff_utc, mi.home_team_id, mi.away_team_id, mi.home_score, mi.away_score, f.event, "
        "       th.name AS home_name, th.short_name AS home_short, th.code AS home_code, "
        "       ta.name AS away_name, ta.short_name AS away_short, ta.code AS away_code "
        "FROM match_intelligence mi JOIN teams th ON th.id = mi.home_team_id JOIN teams ta ON ta.id = mi.away_team_id "
        "LEFT JOIN fixtures f ON f.id = mi.fpl_fixture_id WHERE mi.id = ? AND mi.status = 'FULL_TIME'", (match_id,),
    ).fetchone()
    if m is None:
        return None
    shots = conn.execute(
        "SELECT minute, team_id, player_name, xg, outcome, situation FROM match_shots WHERE match_id = ? AND xg IS NOT NULL "
        "ORDER BY minute", (match_id,),
    ).fetchall()
    if not shots:
        return None
    home_id = m["home_team_id"]
    rows = [
        {
            "minute": s["minute"], "side": "home" if s["team_id"] == home_id else "away", "xg": round(float(s["xg"]), 3),
            "goal": s["outcome"] == "Goal", "player": s["player_name"], "situation": s["situation"],
        }
        for s in shots
    ]
    home_xgs = [r["xg"] for r in rows if r["side"] == "home"]
    away_xgs = [r["xg"] for r in rows if r["side"] == "away"]
    result = deserved_result(home_xgs, away_xgs)
    shot_goals = {"home": sum(1 for r in rows if r["side"] == "home" and r["goal"]), "away": sum(1 for r in rows if r["side"] == "away" and r["goal"])}
    return {
        "match_id": m["id"], "event": m["event"], "kickoff": m["kickoff_utc"],
        "home": {"team_id": home_id, "name": m["home_name"], "short": m["home_short"], "code": m["home_code"], "score": m["home_score"], "xg": round(sum(home_xgs), 2), "shots": len(home_xgs)},
        "away": {"team_id": m["away_team_id"], "name": m["away_name"], "short": m["away_short"], "code": m["away_code"], "score": m["away_score"], "xg": round(sum(away_xgs), 2), "shots": len(away_xgs)},
        "shots": rows,
        "deserved": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in result.items()},
        "own_goals_or_unshot": {
            "home": m["home_score"] - shot_goals["home"], "away": m["away_score"] - shot_goals["away"],
        },
    }
