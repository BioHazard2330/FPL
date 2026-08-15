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


@dataclass(frozen=True)
class PriceForecast:
    player_id: int
    direction: str  # "RISE_LIKELY" | "FALL_LIKELY" | "STABLE"
    momentum_ratio: float
    confidence: str  # always "low" - documented heuristic, not validated


def classify_price_change(conn: sqlite3.Connection, player_id: int) -> PriceForecast:
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
