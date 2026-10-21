"""TONIGHT'S PRICE CHANGES - a probability, fitted on this database's own history.

FPL's price algorithm is unpublished. What the database holds is every player's
cumulative transfers in and out (`player_transfer_momentum_history`, sampled
every sync, 15 minutes during an active window) and every price change
(`player_price_history`). The overnight run happens around 02:30 UTC, so each
night is one observation per player: features read from the last momentum
snapshot before 02:30, label = whether his price moved between then and the
first snapshots after it.

Features, all as a share of the 11M players so a transfer count means the same
for a premium and a budget player: net transfers over the 24 hours to the
snapshot, net transfers since the gameweek deadline, and log ownership. Two
L2-regularised logistic regressions (rise, fall) are fitted on every night but
the last 14, scored on those 14 (ROC AUC, Brier score against the base rate)
and then refitted on everything. Rises are rare this season (tens of events),
so the model is deliberately small: three features, strong regularisation.

Limits: the overnight run's exact time and rule are not public; snapshots are
irregular (the machine is not always on), so a night is used only when a
snapshot within 14 hours precedes 02:30 and one follows it; a night where the
price moved twice is one "moved" label; the held-out window is short, and the
reported skill is for that window. A probability here is a calibrated reading of
past nights, not a guarantee.
"""
import bisect
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.optimize import minimize

RUN_HOUR_UTC = 2.5
MAX_SNAPSHOT_AGE_H = 14.0
MIN_LAG_H = 12.0
LABEL_WINDOW_AFTER_H = 20.0
HOLDOUT_DAYS = 14
MIN_RISES = 20
MIN_FALLS = 40
L2 = 2.0
FEATURES = ("net24", "net_event", "log_own")

_cache: dict = {}


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _total_players(conn: sqlite3.Connection) -> float:
    row = conn.execute("SELECT value FROM app_meta WHERE key = 'total_players'").fetchone()
    return float(row["value"]) if row and float(row["value"]) > 0 else 11_000_000.0


def _series(conn: sqlite3.Connection):
    mom: dict[int, list] = defaultdict(list)
    for r in conn.execute(
        "SELECT player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from "
        "FROM player_transfer_momentum_history ORDER BY valid_from"
    ):
        mom[r["player_id"]].append((_ts(r["valid_from"]), r["transfers_in_event"] or 0, r["transfers_out_event"] or 0, r["transfers_in"] or 0, r["transfers_out"] or 0))
    price: dict[int, list] = defaultdict(list)
    for r in conn.execute("SELECT player_id, value_tenths, valid_from FROM player_price_history ORDER BY valid_from"):
        price[r["player_id"]].append((_ts(r["valid_from"]), r["value_tenths"]))
    own: dict[int, list] = defaultdict(list)
    for r in conn.execute("SELECT player_id, selected_by_percent, valid_from FROM player_ownership_history ORDER BY valid_from"):
        own[r["player_id"]].append((_ts(r["valid_from"]), r["selected_by_percent"] or 0.0))
    return ({k: _Series(v) for k, v in mom.items()}, {k: _Series(v) for k, v in price.items()}, {k: _Series(v) for k, v in own.items()})


class _Series:
    """Time-ordered rows with their timestamps split out once, so a lookup is a bisect, not a rebuild."""

    def __init__(self, rows: list):
        self.rows = rows
        self.keys = [r[0] for r in rows]

    def at(self, t: float):
        i = bisect.bisect_right(self.keys, t) - 1
        return self.rows[i] if i >= 0 else None

    def between(self, lo: float, hi: float):
        a = bisect.bisect_right(self.keys, lo)
        b = bisect.bisect_right(self.keys, hi)
        return self.rows[a:b]


def _features(m0, m24, own_pct: float, total: float) -> list[float]:
    gap_h = (m0[0] - m24[0]) / 3600
    net24 = ((m0[3] - m0[4]) - (m24[3] - m24[4])) * 24 / gap_h
    return [net24 / total * 1e3, (m0[1] - m0[2]) / total * 1e3, float(np.log1p(max(own_pct, 0.0)))]


def training_rows(conn: sqlite3.Connection) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """X, labels (+1 rose, -1 fell, 0 unchanged), night timestamps."""
    total = _total_players(conn)
    mom, price, own = _series(conn)
    first = min((s.keys[0] for s in mom.values() if s.keys), default=None)
    last = max((s.keys[-1] for s in mom.values() if s.keys), default=None)
    if first is None or last is None:
        return np.zeros((0, 3)), np.zeros(0), np.zeros(0)
    day = datetime.fromtimestamp(first, tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=4)
    end = datetime.fromtimestamp(last, tz=timezone.utc)
    X, y, T = [], [], []
    while day <= end:
        t_run = day.timestamp() + RUN_HOUR_UTC * 3600
        for pid, ms in mom.items():
            m0 = ms.at(t_run)
            if m0 is None or t_run - m0[0] > MAX_SNAPSHOT_AGE_H * 3600:
                continue
            after = ms.between(t_run + 1800, t_run + LABEL_WINDOW_AFTER_H * 3600)
            if not after or pid not in price or pid not in own:
                continue
            m24 = ms.at(m0[0] - 24 * 3600)
            if m24 is None or (m0[0] - m24[0]) / 3600 < MIN_LAG_H:
                continue
            p0, p1 = price[pid].at(t_run), price[pid].at(after[0][0])
            o = own[pid].at(t_run)
            if p0 is None or p1 is None or o is None:
                continue
            X.append(_features(m0, m24, o[1], total))
            y.append(int(np.sign(p1[1] - p0[1])))
            T.append(t_run)
        day += timedelta(days=1)
    return np.array(X, dtype=float), np.array(y, dtype=float), np.array(T, dtype=float)


def _fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = L2) -> tuple[np.ndarray, float, np.ndarray, np.ndarray]:
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd

    def loss(w):
        z = Z @ w[:-1] + w[-1]
        p = 1 / (1 + np.exp(-z))
        eps = 1e-12
        nll = -np.sum(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))
        grad_w = Z.T @ (p - y) + l2 * w[:-1]
        grad_b = np.sum(p - y)
        return nll + 0.5 * l2 * np.sum(w[:-1] ** 2), np.concatenate([grad_w, [grad_b]])

    w0 = np.zeros(Z.shape[1] + 1)
    w0[-1] = np.log((y.mean() + 1e-6) / (1 - y.mean() + 1e-6))
    res = minimize(loss, w0, jac=True, method="L-BFGS-B")
    return res.x[:-1], float(res.x[-1]), mu, sd


def _predict(model: dict, X: np.ndarray) -> np.ndarray:
    z = ((X - model["mu"]) / model["sd"]) @ model["w"] + model["b"]
    return 1 / (1 + np.exp(-z))


def _auc(y: np.ndarray, p: np.ndarray) -> float | None:
    pos, neg = p[y == 1], p[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return None
    ranks = np.argsort(np.argsort(np.concatenate([pos, neg]))) + 1
    return float((ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def fit(conn: sqlite3.Connection) -> dict | None:
    X, lab, T = training_rows(conn)
    out: dict = {"rows": int(len(X)), "features": FEATURES, "models": {}}
    if len(X) == 0:
        return None
    cut = T.max() - HOLDOUT_DAYS * 86400
    tr, te = T <= cut, T > cut
    for name, y in (("rise", (lab > 0).astype(float)), ("fall", (lab < 0).astype(float))):
        events = int(y.sum())
        need = MIN_RISES if name == "rise" else MIN_FALLS
        if events < need or y[tr].sum() < 5:
            out["models"][name] = None
            continue
        w, b, mu, sd = _fit_logistic(X[tr], y[tr])
        held = {"w": w, "b": b, "mu": mu, "sd": sd}
        p_te = _predict(held, X[te])
        base = float(y[tr].mean())
        brier = float(np.mean((p_te - y[te]) ** 2))
        brier_base = float(np.mean((base - y[te]) ** 2))
        w2, b2, mu2, sd2 = _fit_logistic(X, y)
        out["models"][name] = {
            "w": w2, "b": b2, "mu": mu2, "sd": sd2, "events": events,
            "holdout": {
                "nights": int(te.sum()), "events": int(y[te].sum()), "auc": _auc(y[te], p_te), "brier": brier, "brier_base_rate": brier_base,
                "skill": (1 - brier / brier_base) if brier_base > 0 else None,
            },
        }
    return out if any(out["models"].values()) else None


META_KEY = "price_model"
REFRESH_AFTER_HOURS = 20.0


def fit_and_store(conn: sqlite3.Connection) -> dict | None:
    import json

    m = fit(conn)
    payload = None
    if m is not None:
        payload = {
            "fitted_at": datetime.now(timezone.utc).isoformat(), "rows": m["rows"], "features": list(FEATURES),
            "models": {
                name: ({"w": [float(x) for x in v["w"]], "b": float(v["b"]), "mu": [float(x) for x in v["mu"]], "sd": [float(x) for x in v["sd"]],
                        "events": v["events"], "holdout": v["holdout"]} if v else None)
                for name, v in m["models"].items()
            },
        }
    conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (META_KEY, json.dumps(payload), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    _cache.clear()
    return payload


def refresh_if_stale(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT updated_at FROM app_meta WHERE key = ?", (META_KEY,)).fetchone()
    if row is not None:
        age_h = (datetime.now(timezone.utc).timestamp() - _ts(row["updated_at"])) / 3600
        if age_h < REFRESH_AFTER_HOURS:
            return False
    fit_and_store(conn)
    return True


def model(conn: sqlite3.Connection) -> dict | None:
    import json

    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (META_KEY,)).fetchone()
    if row is None:
        return None
    if _cache.get("raw") != row["value"]:
        _cache.clear()
        data = json.loads(row["value"]) if row["value"] else None
        if data:
            for v in data["models"].values():
                if v:
                    v["w"], v["mu"], v["sd"] = np.array(v["w"]), np.array(v["mu"]), np.array(v["sd"])
        _cache["raw"], _cache["model"] = row["value"], data
    return _cache["model"]


def usable(m: dict | None, name: str) -> bool:
    """A model is used only if it beat the base rate on the nights it was not fitted on."""
    v = (m or {}).get("models", {}).get(name)
    return bool(v) and (v["holdout"].get("skill") or 0) > 0 and (v["holdout"].get("auc") or 0) >= 0.7


def tonight(conn: sqlite3.Connection, player_ids: list[int] | None = None, now: float | None = None) -> dict[int, dict]:
    """P(rise) and P(fall) at the next overnight run, from each player's latest momentum snapshots (a model that has not earned use reports None)."""
    m = model(conn)
    if m is None:
        return {}
    total = _total_players(conn)
    clock = now or datetime.now(timezone.utc).timestamp()
    since = datetime.fromtimestamp(clock - 60 * 3600, tz=timezone.utc).isoformat()
    marks = ""
    args: list = [since]
    if player_ids is not None:
        marks = f" AND player_id IN ({','.join('?' * len(player_ids))})"
        args += list(player_ids)
    per: dict[int, list] = defaultdict(list)
    for r in conn.execute(
        "SELECT player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from FROM player_transfer_momentum_history "
        f"WHERE valid_from >= ?{marks} ORDER BY valid_from", args,
    ):
        per[r["player_id"]].append((_ts(r["valid_from"]), r["transfers_in_event"] or 0, r["transfers_out_event"] or 0, r["transfers_in"] or 0, r["transfers_out"] or 0))
    own = {r["player_id"]: r["selected_by_percent"] or 0.0 for r in conn.execute("SELECT player_id, selected_by_percent FROM player_ownership_history WHERE valid_until IS NULL")}
    out: dict[int, dict] = {}
    for pid, rows in per.items():
        ser = _Series(rows)
        m0 = rows[-1]
        m24 = ser.at(m0[0] - 24 * 3600)
        if m24 is None or (m0[0] - m24[0]) / 3600 < MIN_LAG_H:
            continue
        x = np.array([_features(m0, m24, own.get(pid, 0.0), total)])
        rec = {"snapshot_age_h": round((clock - m0[0]) / 3600, 1)}
        for name in ("rise", "fall"):
            rec[f"p_{name}"] = float(_predict(m["models"][name], x)[0]) if usable(m, name) else None
        out[pid] = rec
    return out


_tonight_cache: dict = {}
TONIGHT_TTL_SECONDS = 300


def cached_tonight(conn: sqlite3.Connection) -> dict[int, dict]:
    """`tonight` for every player, reused for five minutes so per-player callers do not each re-read the momentum table."""
    import time

    m = model(conn)
    key = (str(conn.execute("PRAGMA database_list").fetchone()[2]), m["fitted_at"] if m else None)
    hit = _tonight_cache.get("entry")
    now = time.time()
    if hit is None or hit["key"] != key or now - hit["at"] > TONIGHT_TTL_SECONDS:
        _tonight_cache["entry"] = {"key": key, "at": now, "data": tonight(conn)}
    return _tonight_cache["entry"]["data"]


def summary(conn: sqlite3.Connection) -> dict | None:
    m = model(conn)
    if m is None:
        return None
    return {
        "fitted_at": m["fitted_at"], "rows": m["rows"], "features": m["features"],
        "models": {
            name: ({"events": v["events"], "usable": usable(m, name), "holdout_events": v["holdout"]["events"], **{k: x for k, x in v["holdout"].items() if k != "events"}} if v else None)
            for name, v in m["models"].items()
        },
    }
