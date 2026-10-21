"""
Price-change forecast (Pillar 1 Plan 1a - spec:
docs/superpowers/specs/2026-08-15-market-rivaling-architecture-design.md, Pillar 1
section). FPL's real price-change trigger algorithm is unpublished and unofficial -
this is an explicitly-uncalibrated, documented heuristic, same honesty posture as
models/differentials.py / traps.py / template.py: a directional signal only, never
a claimed predictor.

Thresholds below are a conservative, documented STARTING POINT, not empirically
fit - no real in-season transfer-momentum data exists yet to calibrate against
(this module was built preseason, before any GW has happened). Recalibrate once
real transfer-momentum data exists, same as expected_points.py's own calibration
history (see MODEL_VERSION there for precedent).
"""

import sqlite3
from dataclasses import dataclass

RISE_THRESHOLD = 0.005  # net transfers this event / total_players
FALL_THRESHOLD = -0.005

# A calibrated probability is only called "likely" at or above this. On the stored
# history the old momentum flag (net transfers above 0.5% of players) was right on
# 5.3% of the nights it fired for a rise and 3.3% for a fall, so the bar is a
# probability, not a ratio.
LIKELY_PROBABILITY = 0.25


@dataclass(frozen=True)
class PriceForecast:
    player_id: int
    direction: str  # "RISE_LIKELY" | "FALL_LIKELY" | "STABLE"
    momentum_ratio: float
    confidence: str  # "low" for the momentum heuristic, "calibrated" when the fitted model decided
    p_rise: float | None = None  # tonight's probability from models/price_model.py, None when the model has not earned use
    p_fall: float | None = None
    calibrated: bool = False


def classify_price_change(conn: sqlite3.Connection, player_id: int) -> PriceForecast:
    from fpl_agent.models import price_model

    model = price_model.model(conn)
    if price_model.usable(model, "rise"):
        p = price_model.cached_tonight(conn).get(player_id)
        if p is not None:
            p_rise, p_fall = p["p_rise"], p["p_fall"]
            direction = "STABLE"
            if p_rise is not None and p_rise >= LIKELY_PROBABILITY and (p_fall is None or p_rise >= p_fall):
                direction = "RISE_LIKELY"
            elif p_fall is not None and p_fall >= LIKELY_PROBABILITY:
                direction = "FALL_LIKELY"
            return PriceForecast(
                player_id=player_id, direction=direction, momentum_ratio=0.0, confidence="calibrated",
                p_rise=round(p_rise, 4) if p_rise is not None else None, p_fall=round(p_fall, 4) if p_fall is not None else None, calibrated=True,
            )
    return _momentum_heuristic(conn, player_id)


def _momentum_heuristic(conn: sqlite3.Connection, player_id: int) -> PriceForecast:
    momentum = conn.execute(
        "SELECT transfers_in_event, transfers_out_event FROM player_transfer_momentum_history "
        "WHERE player_id=? AND valid_until IS NULL",
        (player_id,),
    ).fetchone()
    total_row = conn.execute("SELECT value FROM app_meta WHERE key='total_players'").fetchone()

    if momentum is None or total_row is None or int(total_row["value"]) == 0:
        return PriceForecast(player_id=player_id, direction="STABLE", momentum_ratio=0.0, confidence="low")

    total_players = int(total_row["value"])
    net = momentum["transfers_in_event"] - momentum["transfers_out_event"]
    ratio = net / total_players

    if ratio > RISE_THRESHOLD:
        direction = "RISE_LIKELY"
    elif ratio < FALL_THRESHOLD:
        direction = "FALL_LIKELY"
    else:
        direction = "STABLE"

    return PriceForecast(player_id=player_id, direction=direction, momentum_ratio=round(ratio, 6), confidence="low")
