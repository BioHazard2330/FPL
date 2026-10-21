"""WHICH FOOTBALL SIGNALS PERSIST - measured, not assumed.

A qualitative finding is only worth acting on if the thing it describes repeats.
"Brighton scored four from 2.2 xG" and "Leeds took 83% of their xG from dead
balls" are different claims about the future, and this module measures how much
each kind carries into the next match.

Method: for every team, in match order, take the mean of its previous matches
(at least three) as the prediction and the next match's value as the outcome. The
reliability of a metric is the Pearson correlation between the two across all
team-matches, with a Fisher-z 90% interval; the slope is how far one unit of the
prior mean moves the next match. Two samples:

- this season's shot-level metrics, from stored `match_story` rows (set-piece
  share, header share, outside-the-box share, finishing, and so on). Small: one
  season of 20 teams, so the intervals are wide and the verdict says so.
- the Understat history (every stored season) for the metrics it carries: team
  xG for and against, goals minus xG, and per-player shot and xG rates. Large
  samples, and the reference the small one is read against.

Verdict (a judgement, not a fitted cut): `persistent` when the interval's lower
bound is above 0.10, `none` when its upper bound is below 0.10, `unclear`
otherwise, and `too few` under 30 pairs. Nothing here changes a projection; it
labels how much weight a finding deserves.
"""
import json
import math
import sqlite3

import numpy as np

MIN_PRIOR = 3
MIN_PAIRS = 30
PERSISTENT_LOWER = 0.10

LABELS = {
    "xg": "chances created", "xg_against": "chances conceded", "shots": "shot volume", "xg_per_shot": "chance quality per shot",
    "dead_ball_xg_share": "share of xG from dead balls", "dead_ball_xga_share": "share of xG conceded from dead balls",
    "fast_break_xg_share": "share of xG on the break", "header_xg_share": "share of xG from headers",
    "box_xg_share": "share of xG from inside the box", "outside_box_shot_share": "share of shots from outside the box",
    "goals_minus_xg": "goals above or below xG", "conceded_minus_xga": "goals conceded above or below xG against",
    "first_half_xg_share": "share of xG in the first half", "best_spell_share": "share of xG in the best ten minutes",
    "player_shots_per90": "a player's shots per 90", "player_xg_per90": "a player's xG per 90",
}
STORY_METRICS = [
    "xg", "xg_against", "shots", "xg_per_shot", "dead_ball_xg_share", "dead_ball_xga_share", "fast_break_xg_share", "header_xg_share",
    "box_xg_share", "outside_box_shot_share", "goals_minus_xg", "conceded_minus_xga", "first_half_xg_share", "best_spell_share",
]
IMPLICATION = {
    "persistent": "carries into the next match: weight it",
    "unclear": "may carry a little: treat as a watch item",
    "none": "does not carry: a single match says nothing about the next",
    "too few": "not enough matches to say",
}


def fisher_interval(r: float, n: int, z: float = 1.645) -> tuple[float, float]:
    if n <= 3 or abs(r) >= 0.9999:
        return (-1.0, 1.0)
    center = math.atanh(r)
    half = z / math.sqrt(n - 3)
    return (math.tanh(center - half), math.tanh(center + half))


def verdict(r: float | None, n: int) -> str:
    if r is None or n < MIN_PAIRS:
        return "too few"
    lo, hi = fisher_interval(r, n)
    if lo > PERSISTENT_LOWER:
        return "persistent"
    if hi < PERSISTENT_LOWER:
        return "none"
    return "unclear"


def _stat(xs: list[float], ys: list[float], source: str) -> dict:
    n = len(xs)
    if n < 5:
        return {"n": n, "r": None, "slope": None, "ci": None, "verdict": "too few", "source": source}
    x, y = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    if x.std() == 0 or y.std() == 0:
        return {"n": n, "r": None, "slope": None, "ci": None, "verdict": "too few", "source": source}
    r = float(np.corrcoef(x, y)[0, 1])
    slope = float(np.polyfit(x, y, 1)[0])
    lo, hi = fisher_interval(r, n)
    return {"n": n, "r": round(r, 3), "slope": round(slope, 3), "ci": [round(lo, 3), round(hi, 3)], "verdict": verdict(r, n), "source": source}


def prior_mean_pairs(series: dict, min_prior: int = MIN_PRIOR) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    for values in series.values():
        vals = [v for v in values if v is not None]
        for i in range(min_prior, len(vals)):
            xs.append(float(np.mean(vals[:i])))
            ys.append(float(vals[i]))
    return xs, ys


def story_series(conn: sqlite3.Connection) -> dict[str, dict]:
    series: dict[str, dict[int, list]] = {m: {} for m in STORY_METRICS}
    rows = conn.execute(
        "SELECT ms.story_json, mi.kickoff_utc FROM match_story ms JOIN match_intelligence mi ON mi.id = ms.match_id "
        "WHERE mi.status = 'FULL_TIME' ORDER BY mi.kickoff_utc, mi.id"
    ).fetchall()
    for row in rows:
        story = json.loads(row["story_json"])
        for side in ("home", "away"):
            tid = story["match"][side]["team_id"]
            metrics = dict(story["metrics"][side])
            spell = (story.get("spells") or {}).get(side)
            metrics["best_spell_share"] = spell["share"] if spell else None
            for name in STORY_METRICS:
                series[name].setdefault(tid, []).append(metrics.get(name))
    return series


def story_reliability(conn: sqlite3.Connection) -> dict[str, dict]:
    out = {}
    for name, per_team in story_series(conn).items():
        xs, ys = prior_mean_pairs(per_team)
        out[name] = _stat(xs, ys, "this season's shots")
    return out


def history_reliability(conn: sqlite3.Connection) -> dict[str, dict]:
    """Team xG for/against and finishing across every stored season, and player shot/xG rates."""
    out: dict[str, dict] = {}
    rows = conn.execute(
        "SELECT season, understat_match_id AS mid, market_team_id AS team, MIN(match_date) AS d, SUM(xg) AS xg, SUM(goals) AS goals "
        "FROM player_match_stats_history WHERE market_team_id IS NOT NULL AND xg IS NOT NULL GROUP BY season, understat_match_id, market_team_id"
    ).fetchall()
    by_match: dict[tuple, list] = {}
    for r in rows:
        by_match.setdefault((r["season"], r["mid"]), []).append(r)
    team_series: dict[str, dict] = {"xg": {}, "xg_against": {}, "goals_minus_xg": {}, "conceded_minus_xga": {}}
    for (season, _mid), sides in sorted(by_match.items(), key=lambda kv: min(s["d"] for s in kv[1])):
        if len(sides) != 2:
            continue
        for me, opp in ((sides[0], sides[1]), (sides[1], sides[0])):
            key = (season, me["team"])
            team_series["xg"].setdefault(key, []).append(me["xg"])
            team_series["xg_against"].setdefault(key, []).append(opp["xg"])
            team_series["goals_minus_xg"].setdefault(key, []).append(me["goals"] - me["xg"])
            team_series["conceded_minus_xga"].setdefault(key, []).append(opp["goals"] - opp["xg"])
    for name, per_team in team_series.items():
        xs, ys = prior_mean_pairs(per_team)
        out[name] = _stat(xs, ys, "Understat team-matches, all stored seasons")

    players: dict[tuple, list] = {}
    for r in conn.execute(
        "SELECT player_id, season, minutes, shots, xg FROM player_match_stats_history WHERE player_id IS NOT NULL AND minutes >= 45 "
        "ORDER BY match_date, id"
    ):
        players.setdefault((r["player_id"], r["season"]), []).append((r["shots"] * 90.0 / r["minutes"], r["xg"] * 90.0 / r["minutes"]))
    for idx, name in ((0, "player_shots_per90"), (1, "player_xg_per90")):
        xs: list[float] = []
        ys: list[float] = []
        for vals in players.values():
            seq = [v[idx] for v in vals]
            for i in range(5, len(seq)):
                xs.append(float(np.mean(seq[:i])))
                ys.append(float(seq[i]))
        out[name] = _stat(xs, ys, "Understat player-matches (45+ minutes), all stored seasons")
    return out


def reliability(conn: sqlite3.Connection) -> dict:
    stats = story_reliability(conn)
    for name, stat in history_reliability(conn).items():
        if name in stats and stats[name]["verdict"] != "too few":
            stat["season_sample"] = stats[name]
        stats[name] = stat
    for name, stat in stats.items():
        stat["label"] = LABELS.get(name, name)
        stat["implication"] = IMPLICATION[stat["verdict"]]
    return {"metrics": stats, "min_prior_matches": MIN_PRIOR, "min_pairs": MIN_PAIRS}


FINDING_METRIC = {
    "dead_ball_xg_share": "dead_ball_xg_share", "dead_ball_xga_share": "dead_ball_xga_share", "goals_minus_xg": "goals_minus_xg",
    "best_spell_share": "best_spell_share", "player_shots_per90": "player_shots_per90", "player_xg_per90": "player_xg_per90",
}


def annotate_story(story: dict, rel: dict) -> dict:
    """Attach each finding's measured persistence and cap its confidence where the signal does not carry."""
    metrics = rel["metrics"]
    for f in story["findings"]:
        key = f.get("metric")
        stat = metrics.get(key) if key else None
        if not stat:
            f.pop("reliability", None)
            continue
        f["reliability"] = {"metric": key, "label": stat["label"], "r": stat["r"], "n": stat["n"], "verdict": stat["verdict"], "source": stat["source"]}
        if stat["verdict"] in ("none", "too few") and f["confidence"] != "high":
            f["confidence"] = "low"
    return story


def reliability_sentence(f: dict) -> str | None:
    rel = f.get("reliability")
    if not rel:
        return None
    if rel["r"] is None:
        return f"Reliability of {rel['label']}: too few matches to measure."
    who = "a player's" if rel["metric"].startswith("player") else "a side's"
    unit = "player-matches" if rel["metric"].startswith("player") else "team-matches"
    return f"Reliability of {rel['label']}: r = {rel['r']:+.2f} between {who} prior average and the next match over {rel['n']} {unit} ({rel['verdict']})."
