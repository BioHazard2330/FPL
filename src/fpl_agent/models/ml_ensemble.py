"""Gradient-boosted challenger to calibrated-v2's hand-tuned linear point
formula (competitor-architecture research, 2026-08-20 - see CLAUDE.md).
OpenFPL (arxiv 2508.09992) benchmarks a position-aware XGBoost/RandomForest
ensemble against a leading commercial FPL service and specifically beats it on
high-return players (>2 points) - the exact bucket this project's own
now-corrected backtest showed calibrated-v2 merely TYING a naive baseline on
(MAE 3.81 vs 3.79, n=785, see CLAUDE.md).

Deliberately uses the SAME leakage-safe feature ingredients
`backtesting/harness.py::run_backtest` already computes for its linear
formula (personal shrunk/raw per-90 rates, minutes-bucket probabilities,
position, the season's real scoring-rate constants) rather than adding new
signal - this isolates the actual question being tested (does a learned
nonlinear model beat a fixed-form linear blend of the SAME inputs), not
"does more data help" which would be a different, more expensive experiment.
Predicts the identical "core" target `reconstruct_actual_points` already
defines (appearance + goals + assists + cards - no bonus/clean-sheets/defcon,
same harness-wide scope limit), so its MAE is directly comparable to a
calibrated-v2 `fpl backtest` run on the same held-out season.

Not wired into any live command yet - this module is the training/evaluation
harness for deciding WHETHER to promote it, matching this project's own rule
(models/rules.py's whole "never fabricate/never overstate confidence"
posture): a model only ships once it's beaten calibrated-v2 on genuinely
held-out data, not on the training season."""
import sqlite3

import numpy as np

from fpl_agent.backtesting.harness import (
    _PARTIAL_MINUTES_FRACTION,
    _position,
    _round_start_dates,
    _scoring_rates,
    reconstruct_actual_points,
)
from fpl_agent.models.minutes_distribution import expected_appearance_points, minutes_bucket_probabilities
from fpl_agent.models.player_regression import player_shrunk_rates

FEATURE_NAMES = [
    "is_gkp", "is_def", "is_mid", "is_fwd",
    "shrunk_goals_per90", "raw_goals_per90",
    "shrunk_assists_per90", "raw_assists_per90",
    "shrunk_cards_per90", "raw_cards_per90",
    "p_full", "p_partial", "effective_minutes_fraction",
    "goals_rate", "assists_rate", "yellow_card_rate",
    "appearance",
]
_POSITIONS = ("GKP", "DEF", "MID", "FWD")


def _feature_row(conn: sqlite3.Connection, player_id: int, season: str, position: str, as_of_date: str) -> list[float] | None:
    """None means leakage-excluded (same bar run_backtest applies - fewer
    than 4 pre-cutoff empirical matches would otherwise pull in live,
    undated state via expected_minutes())."""
    mp = minutes_bucket_probabilities(conn, player_id, season, as_of_date=as_of_date)
    if mp.source != "empirical":
        return None

    shrunk = player_shrunk_rates(conn, player_id, season, as_of_date=as_of_date)
    goals_rate, assists_rate, yellow_card_rate = _scoring_rates(conn, season, position)
    effective_minutes_fraction = mp.p_partial * _PARTIAL_MINUTES_FRACTION + mp.p_full
    appearance = expected_appearance_points(mp)

    return [
        1.0 if position == "GKP" else 0.0,
        1.0 if position == "DEF" else 0.0,
        1.0 if position == "MID" else 0.0,
        1.0 if position == "FWD" else 0.0,
        shrunk["goals"].shrunk_per90, shrunk["goals"].raw_per90,
        shrunk["assists"].shrunk_per90, shrunk["assists"].raw_per90,
        shrunk["cards"].shrunk_per90, shrunk["cards"].raw_per90,
        mp.p_full, mp.p_partial, effective_minutes_fraction,
        goals_rate, assists_rate, yellow_card_rate,
        appearance,
    ]


def build_dataset(conn: sqlite3.Connection, seasons: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Walks every season the same round-chunked, as_of_date-threaded way
    run_backtest does (one call per season, concatenated) - no future data
    ever crosses a round boundary within a season, and cross-season leakage
    is structurally impossible since each season's own match_date range is
    disjoint and as_of_date is always scoped to that season's own rows."""
    X_rows, y_rows = [], []
    for season in seasons:
        starts = _round_start_dates(conn, season)
        if not starts:
            continue
        boundaries = starts + [None]
        for i in range(len(starts)):
            round_start, round_end = boundaries[i], boundaries[i + 1]
            clause = "AND match_date < ?" if round_end else ""
            params = (season, round_start) + ((round_end,) if round_end else ())
            rows = conn.execute(
                f"SELECT * FROM player_match_stats_history WHERE season=? AND match_date >= ? {clause}", params,
            ).fetchall()
            for row in rows:
                if row["player_id"] is None:
                    continue
                position = _position(conn, row["player_id"])
                if position is None or position not in _POSITIONS:
                    continue
                actual = reconstruct_actual_points(conn, row, season)
                if actual is None:
                    continue
                features = _feature_row(conn, row["player_id"], season, position, round_start)
                if features is None:
                    continue
                X_rows.append(features)
                y_rows.append(actual)

    return np.array(X_rows, dtype=np.float64), np.array(y_rows, dtype=np.float64)


def train(X: np.ndarray, y: np.ndarray):
    """Modest, sensible defaults (not Optuna-tuned - a real follow-up, not
    needed to answer the core "does the model class help" question this
    first pass exists to answer). Shallow-ish trees + a real L2 term guard
    against overfitting a training set this size (a few tens of thousands of
    rows) relative to a 17-feature space."""
    import xgboost as xgb

    model = xgb.XGBRegressor(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, reg_lambda=1.5,
        objective="reg:squarederror", random_state=42,
    )
    model.fit(X, y)
    return model


def evaluate(model, X: np.ndarray, y: np.ndarray) -> dict:
    pred = model.predict(X)
    errors = pred - y
    high_mask = y > 2
    low_mask = ~high_mask
    return {
        "n": len(y),
        "mae": float(np.mean(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(errors**2))),
        "high_return_n": int(high_mask.sum()),
        "high_return_mae": float(np.mean(np.abs(errors[high_mask]))) if high_mask.any() else None,
        "low_return_n": int(low_mask.sum()),
        "low_return_mae": float(np.mean(np.abs(errors[low_mask]))) if low_mask.any() else None,
    }
