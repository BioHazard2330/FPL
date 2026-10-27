"""HOW GOOD WAS THE PROJECTION FOR ONE FINISHED GAMEWEEK?

Every settled `prediction_outcomes` row of one gameweek and one model version, scored against a season-average baseline
(each player's mean points over earlier gameweeks) and against what decisions are actually about: the players projected at
`CONTENDER_XP` or more. A rank correlation over everyone mostly measures who plays and in what position; among the
contenders it measures what a transfer or an armband needs. First read, GW8 2026/27 (calibrated-v3): across everyone
Spearman 0.62, among 186 contenders 0.175 (baseline 0.078), their top 20 realising 3.35 points against 3.46 for all of them."""
import sqlite3

import numpy as np
from scipy.stats import spearmanr

CONTENDER_XP = 2.0


def _rho(a, b) -> float | None:
    if len(a) < 5:
        return None
    r = spearmanr(a, b).correlation
    return None if r != r else round(float(r), 3)


def gameweek_skill(conn: sqlite3.Connection, event: int) -> dict | None:
    rows = conn.execute(
        "SELECT po.player_id, po.predicted_median AS pm, po.actual_points AS ap, po.actual_minutes AS am, "
        "po.predicted_expected_minutes AS pem, p.element_type AS et "
        "FROM prediction_outcomes po JOIN players p ON p.id = po.player_id "
        "WHERE po.event = ? AND po.actual_points IS NOT NULL AND po.predicted_median IS NOT NULL "
        "AND po.model_version = (SELECT model_version FROM prediction_outcomes WHERE event = ? AND model_version IS NOT NULL "
        "GROUP BY model_version ORDER BY COUNT(*) DESC LIMIT 1)", (event, event),
    ).fetchall()
    if len(rows) < 20:
        return None
    earlier: dict[int, list[int]] = {}
    for r in conn.execute("SELECT player_id, total_points FROM player_gw_stats WHERE event < ?", (event,)):
        earlier.setdefault(r["player_id"], []).append(r["total_points"])
    pm = np.array([r["pm"] for r in rows], float)
    ap = np.array([r["ap"] for r in rows], float)
    base = np.array([np.mean(earlier[r["player_id"]]) if earlier.get(r["player_id"]) else 0.0 for r in rows])
    et = np.array([r["et"] for r in rows])
    am = np.array([r["am"] or 0 for r in rows], float)
    pem = np.array([r["pem"] or 0 for r in rows], float)
    rel = pm >= CONTENDER_XP
    out = {
        "event": event, "n": len(rows), "contenders": int(rel.sum()),
        "bias_all": round(float((ap - pm).mean()), 2),
        "mae_all": round(float(np.abs(pm - ap).mean()), 3), "mae_baseline_all": round(float(np.abs(base - ap).mean()), 3),
        "spearman_all": _rho(pm, ap), "spearman_baseline_all": _rho(base, ap),
    }
    if rel.sum() >= 5:
        order = np.argsort(-pm[rel])
        top = min(20, int(rel.sum()))
        out.update({
            "mae_contenders": round(float(np.abs(pm[rel] - ap[rel]).mean()), 3),
            "mae_baseline_contenders": round(float(np.abs(base[rel] - ap[rel]).mean()), 3),
            "spearman_contenders": _rho(pm[rel], ap[rel]), "spearman_baseline_contenders": _rho(base[rel], ap[rel]),
            "contenders_mean_actual": round(float(ap[rel].mean()), 2),
            f"top{top}_mean_actual": round(float(ap[rel][order[:top]].mean()), 2),
            "minutes_predicted": round(float(pem[rel].mean()), 1), "minutes_actual": round(float(am[rel].mean()), 1),
        })
        out["bias_by_position"] = {
            lab: round(float((ap[rel & (et == t)] - pm[rel & (et == t)]).mean()), 2)
            for t, lab in ((1, "GKP"), (2, "DEF"), (3, "MID"), (4, "FWD")) if (rel & (et == t)).sum() >= 5
        }
    return out
