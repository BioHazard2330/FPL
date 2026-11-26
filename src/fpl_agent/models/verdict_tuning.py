"""The verdict's lens weights refitted on this season's settled weeks (2026-11-26, the manager: judge on this season).

Each settled gameweek (GW8 on, 450+ minutes before it) every player's lenses are rebuilt from what was known at its
deadline - the frozen projection, FPL points per 90 (season and last six), points per £m, his mean miss against earlier
frozen projections, his start share over the last five - as percentiles within his position. A weighting is scored by
what the top eight per position actually scored that week. The fixtures lens is not rebuilt (no as-of fixture rating is
stored), so it keeps its 0.15 and the other five share 0.85.

Weights change only when they win on weeks they were not fitted on: each week is held out in turn, the best weights on
the others score it, and the refit is adopted only if that held-out mean beats the live weights' by `MARGIN`. First fit,
GW8-11: live 4.48 points a pick, projection alone 4.51, the best 0.9 model / 0.1 nailed 4.79; points per 90 took no
weight in any of the top weightings."""
import itertools
import sqlite3

import numpy as np

LENSES = ("expected", "returns", "value", "track", "security")
LIVE = {"expected": 0.30, "returns": 0.20, "value": 0.10, "track": 0.10, "fixtures": 0.15, "security": 0.15}
FIXTURES = 0.15
STEP = 0.1
MARGIN = 0.1
TOP = 8


def _rows(conn: sqlite3.Connection, season: str) -> list[dict]:
    pos = {r[0]: r[1] for r in conn.execute(
        "SELECT p.id, et.singular_name_short FROM players p JOIN element_types et ON et.id = p.element_type")}
    price = {r[0]: r[1] / 10 for r in conn.execute("SELECT player_id, value_tenths FROM player_price_history WHERE valid_until IS NULL")}
    gw: dict[int, list[tuple]] = {}
    for pid, e, m, p, st in conn.execute(
        "SELECT player_id, event, minutes, total_points, starts FROM player_gw_stats WHERE season = ? AND fixtures > 0 ORDER BY event", (season,)):
        gw.setdefault(pid, []).append((e, m or 0, p or 0, min(st or 0, 1)))
    po: dict[int, list[tuple]] = {}
    for pid, e, p, a in conn.execute(
        "SELECT player_id, event, predicted_median, actual_points FROM prediction_outcomes WHERE season = ? "
        "AND actual_points IS NOT NULL AND predicted_median IS NOT NULL ORDER BY event", (season,)):
        po.setdefault(pid, []).append((e, p, a))
    rows = []
    for pid, hist in po.items():
        for e, pred, act in hist:
            h = [r for r in gw.get(pid, []) if r[0] < e]
            mins = sum(r[1] for r in h)
            if mins < 450:
                continue
            l6 = h[-6:]
            m6 = sum(r[1] for r in l6)
            s90 = sum(r[2] for r in h) / mins * 90
            l90 = sum(r[2] for r in l6) / m6 * 90 if m6 >= 180 else s90
            miss = [a - p for ee, p, a in hist if ee < e][-8:]
            sh = [r[3] for r in h][-5:]
            rows.append({"e": e, "pos": pos.get(pid), "act": act, "expected": pred, "returns": (s90 + l90) / 2,
                         "value": sum(r[2] for r in h) / max(price.get(pid, 5.0), 3.5),
                         "track": float(np.mean(miss)) if len(miss) >= 2 else None,
                         "security": sum(sh) / len(sh) if len(sh) >= 3 else None})
    return rows


def _percentiles(rows: list[dict]) -> dict[str, np.ndarray]:
    out = {k: np.full(len(rows), np.nan) for k in LENSES}
    groups: dict[tuple, list[int]] = {}
    for i, r in enumerate(rows):
        groups.setdefault((r["e"], r["pos"]), []).append(i)
    for idx in groups.values():
        for k in LENSES:
            v = np.array([np.nan if rows[i][k] is None else rows[i][k] for i in idx], float)
            ok = ~np.isnan(v)
            if ok.sum() > 1:
                vals = np.full(len(idx), np.nan)
                vals[ok] = np.argsort(np.argsort(v[ok])) / (ok.sum() - 1) * 100
                out[k][idx] = vals
    return out


def fit(conn: sqlite3.Connection, season: str) -> dict | None:
    rows = _rows(conn, season)
    weeks = sorted({r["e"] for r in rows})
    if len(weeks) < 3 or len(rows) < 300:
        return None
    pct = _percentiles(rows)
    E = np.array([r["e"] for r in rows])
    A = np.array([r["act"] for r in rows], float)
    POS = np.array([r["pos"] for r in rows])

    def composite(w):
        num = np.zeros(len(rows))
        den = np.zeros(len(rows))
        for k, wk in zip(LENSES, w):
            ok = ~np.isnan(pct[k])
            num[ok] += wk * pct[k][ok]
            den[ok] += wk
        return np.where(den > 0, num / np.maximum(den, 1e-9), np.nan)

    def score(w, keep):
        sc = composite(w)
        out = []
        for t in keep:
            for ps in ("GKP", "DEF", "MID", "FWD"):
                m = (E == t) & (POS == ps) & ~np.isnan(sc)
                if m.sum():
                    out.append(A[m][np.argsort(-sc[m])[:TOP]].mean())
        return float(np.mean(out)) if out else 0.0

    steps = np.round(np.arange(0, 1 + 1e-9, STEP), 2)
    grid = [w for w in itertools.product(steps, repeat=len(LENSES)) if abs(sum(w) - 1) < 1e-6]
    live = tuple(LIVE[k] for k in LENSES)
    held_fit, held_live = [], []
    for t in weeks:
        others = [u for u in weeks if u != t]
        best = max(grid, key=lambda w: score(w, others))
        held_fit.append(score(best, [t]))
        held_live.append(score(live, [t]))
    best_all = max(grid, key=lambda w: score(w, weeks))
    adopt = float(np.mean(held_fit)) - float(np.mean(held_live)) >= MARGIN
    weights = {k: round(float(v) * (1 - FIXTURES), 3) for k, v in zip(LENSES, best_all)} if adopt else {k: LIVE[k] for k in LENSES}
    weights["fixtures"] = FIXTURES
    return {"weights": weights, "adopted": adopt, "held_out_fit": round(float(np.mean(held_fit)), 3),
            "held_out_live": round(float(np.mean(held_live)), 3), "best_in_sample": dict(zip(LENSES, map(float, best_all))),
            "weeks": weeks}
