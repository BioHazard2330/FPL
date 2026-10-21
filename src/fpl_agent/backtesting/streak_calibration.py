"""How much does a two-match streak move the next match? Measured, so the qualitative adjustment is sized by data.

`qualitative_feed.py` adds a fraction of a player's goals or assists component
when a PERSISTENT_TREND (two or more matches pointing the same way) exists. That
fraction was 0.35 for every signal, a judgement that was never checked. This
module checks it on the Understat player-match history.

Method, per signal and direction:
- A player's baseline is an empirical-Bayes rate: (his season-to-date total +
  m x the league rate for his position) / (his season-to-date 90s + m), with m
  chosen on the whole sample to minimise minutes-weighted squared error. That is
  what a flat, shrunk season rate predicts, the thing the projection already
  does, and it includes the streak matches themselves.
- The streak is defined the way the detector defines it
  (`statistical_evidence`: 3+ shots or 0.30+ xG, 2+ key passes or 0.15+ xA, in
  each of two consecutive matches) or, for the negative direction, two
  consecutive 60+ minute matches with no shot (goals) or no key pass and under
  0.03 xA (assists).
- The ratio is realised next-match output over baseline, minutes-weighted, with
  a 90% bootstrap interval. Ratio 1.00 means the baseline already knew; the
  adjustment worth applying is the gap from 1.

Limits: matches are the history table's only (a player who did not play has no
row); only players with 45+ minutes in the next match are scored; the baseline
is a flat shrunk rate, not the full projection, so a ratio above 1 means
"under-reacts to the streak relative to a flat rate", which is the question the
adjustment answers.
"""
import sqlite3

import numpy as np

SHRINK_GRID = (0, 1, 2, 3, 4, 6, 8, 12, 16, 24)
MIN_NEXT_MINUTES = 45
MIN_STREAK_PAIRS = 30


def _hot_goal_threat(a, b) -> bool:
    return all((m["shots"] or 0) >= 3 or (m["xg"] or 0) >= 0.30 for m in (a, b))


def _cold_goal_threat(a, b) -> bool:
    return all((m["minutes"] or 0) >= 60 and (m["shots"] or 0) == 0 for m in (a, b))


def _hot_creation(a, b) -> bool:
    return all((m["key_passes"] or 0) >= 2 or (m["xa"] or 0) >= 0.15 for m in (a, b))


def _cold_creation(a, b) -> bool:
    return all((m["minutes"] or 0) >= 60 and (m["key_passes"] or 0) == 0 and (m["xa"] or 0) < 0.03 for m in (a, b))


STREAKS = {
    ("GOAL_THREAT", "POSITIVE"): ("goals", _hot_goal_threat, "two straight matches with 3+ shots or 0.30+ xG"),
    ("GOAL_THREAT", "NEGATIVE"): ("goals", _cold_goal_threat, "two straight 60+ minute matches with no shot"),
    ("CREATION", "POSITIVE"): ("assists", _hot_creation, "two straight matches with 2+ key passes or 0.15+ xA"),
    ("CREATION", "NEGATIVE"): ("assists", _cold_creation, "two straight 60+ minute matches with no key pass and under 0.03 xA"),
}


def _load(conn: sqlite3.Connection):
    pos = {r["id"]: r["element_type"] for r in conn.execute("SELECT id, element_type FROM players")}
    seqs: dict[tuple, list] = {}
    for r in conn.execute(
        "SELECT player_id, season, minutes, goals, assists, shots, xg, xa, key_passes FROM player_match_stats_history "
        "WHERE player_id IS NOT NULL AND minutes IS NOT NULL ORDER BY season, match_date, id"
    ):
        seqs.setdefault((r["player_id"], r["season"]), []).append(r)
    return pos, seqs


def streak_table(conn: sqlite3.Connection, bootstraps: int = 400, seed: int = 11) -> dict:
    pos, seqs = _load(conn)
    metrics = ("goals", "assists")
    cum_rows = []
    for (pid, _season), matches in seqs.items():
        p = pos.get(pid)
        if p is None:
            continue
        played = [m for m in matches if m["minutes"] >= MIN_NEXT_MINUTES]
        if len(played) < 4:
            continue
        sums = {k: np.cumsum([m[k] or 0 for m in played]) for k in metrics}
        mins90 = np.cumsum([m["minutes"] for m in played]) / 90.0
        for i in range(1, len(played) - 1):
            nxt = played[i + 1]
            flags = {key: bool(spec[1](played[i - 1], played[i])) for key, spec in STREAKS.items()}
            cum_rows.append((p, mins90[i], nxt["minutes"], {k: sums[k][i] for k in metrics}, {k: (nxt[k] or 0) * 90.0 / nxt["minutes"] for k in metrics}, flags))
    if not cum_rows:
        return {"shrink": {}, "rows": [], "pairs": 0}
    P = np.array([r[0] for r in cum_rows])
    M90 = np.array([r[1] for r in cum_rows])
    W = np.array([r[2] for r in cum_rows]) / 90.0
    chosen: dict[str, float] = {}
    base: dict[str, np.ndarray] = {}
    nxt_vals: dict[str, np.ndarray] = {}
    for metric in metrics:
        S = np.array([r[3][metric] for r in cum_rows])
        N = np.array([r[4][metric] for r in cum_rows])
        league = {int(p): (S[P == p].sum() / M90[P == p].sum()) if (P == p).any() else 0.0 for p in (1, 2, 3, 4)}
        mu = np.array([league[int(p)] for p in P])
        best = None
        for m in SHRINK_GRID:
            b = (S + m * mu) / (M90 + m)
            mse = float(np.sum(W * (N - b) ** 2) / W.sum())
            if best is None or mse < best[0]:
                best = (mse, m, b)
        chosen[metric] = best[1]
        base[metric] = best[2]
        nxt_vals[metric] = N
    rng = np.random.default_rng(seed)
    rows = []
    for key, (metric, _fn, label) in STREAKS.items():
        mask = np.array([r[5][key] for r in cum_rows])
        idx_all = np.where(mask)[0]
        n = len(idx_all)
        if n < MIN_STREAK_PAIRS:
            rows.append({"signal": key[0], "direction": key[1], "streak": label, "metric": metric, "n": n, "ratio": None, "ci": None})
            continue
        b, y = base[metric], nxt_vals[metric]
        denominator = (b[idx_all] * W[idx_all]).sum()
        if denominator <= 0:
            rows.append({"signal": key[0], "direction": key[1], "streak": label, "metric": metric, "n": n, "ratio": None, "ci": None})
            continue
        ratio = float((y[idx_all] * W[idx_all]).sum() / denominator)
        boots = []
        for _ in range(bootstraps):
            idx = rng.choice(idx_all, n)
            boots.append((y[idx] * W[idx]).sum() / max((b[idx] * W[idx]).sum(), 1e-12))
        lo, hi = np.percentile(boots, [5, 95])
        rows.append({"signal": key[0], "direction": key[1], "streak": label, "metric": metric, "n": n, "ratio": round(ratio, 3), "ci": [round(float(lo), 3), round(float(hi), 3)]})
    return {"shrink": chosen, "rows": rows, "pairs": len(cum_rows)}


def suggested_fraction(row: dict) -> float | None:
    """The adjustment the streak's own data supports: the gap from 1.00 in the claimed direction, to the nearest 0.05, zero if the interval spans 1."""
    if row["ratio"] is None:
        return None
    lo, hi = row["ci"]
    sign = 1.0 if row["direction"] == "POSITIVE" else -1.0
    if lo <= 1.0 <= hi:
        return 0.0
    gap = (row["ratio"] - 1.0) * sign
    return round(max(gap, 0.0) * 20) / 20
