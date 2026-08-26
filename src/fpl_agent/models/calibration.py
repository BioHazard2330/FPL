"""Calibration/learning persistent storage (2026-08-26, GW1-postmortem pass,
section R). Real, explicit scope: store real prediction-vs-outcome data for
future calibration - never fit a statistical calibration model from this
(one gameweek is nowhere near enough real data to calibrate against
honestly, same discipline `price_forecast.py`/`squad_churn.py` already
apply). Two halves, deliberately separate calls at two different real
lifecycle moments:

- `record_predictions_for_locked_squad(conn, event)` - snapshots the model's
  own current `expected_points()` for the locked squad's real players, once,
  near the gameweek's deadline (wired into `run_scheduled` at the LOCKED
  lifecycle state). This is the genuine "what did we predict going in" side
  - it cannot be reconstructed after the fact once real results exist.
- `record_outcomes_for_finished_event(conn, event)` - fills in the real
  actual outcome (points/minutes from `player_stats_snapshot`, plus whatever
  real qualitative/user signal exists) once the gameweek has finished. Only
  ever writes the outcome columns of an existing row (or creates a
  prediction-less row when none exists - the honest state for GW1, whose
  deadline passed before this table existed at all: no fabricated
  "predicted_median", the outcome side is still real and worth keeping).

Idempotent both ways (UNIQUE(player_id, event, season)) - safe to call on
every scheduled cycle."""
import sqlite3
from datetime import datetime, timezone

from fpl_agent.models.expected_points import expected_points
from fpl_agent.models.rules import current_season


def record_predictions_for_locked_squad(conn: sqlite3.Connection, event: int, squad_ids: list[int]) -> int:
    """Real, one-time-per-(player,event) snapshot - a genuine no-op (0 rows
    written) if predictions for this event were already recorded, so calling
    this on every scheduled cycle while a gameweek stays LOCKED never
    re-writes a real prediction with a later, hindsight-influenced number."""
    if not squad_ids:
        return 0
    season = current_season(conn)
    now = datetime.now(timezone.utc).isoformat()
    written = 0
    for player_id in squad_ids:
        existing = conn.execute(
            "SELECT 1 FROM prediction_outcomes WHERE player_id=? AND event=? AND season=?",
            (player_id, event, season),
        ).fetchone()
        if existing is not None:
            continue
        try:
            ep = expected_points(conn, player_id, n_gw=1)
        except Exception:
            continue
        conn.execute(
            "INSERT INTO prediction_outcomes (player_id, event, season, predicted_median, predicted_floor, "
            "predicted_ceiling, predicted_confidence, predicted_expected_minutes, model_version, predicted_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (player_id, event, season, ep.median, ep.floor, ep.ceiling, ep.confidence,
             ep.expected_minutes, ep.model_version, now),
        )
        written += 1
    if written:
        conn.commit()
    return written


def record_outcomes_for_finished_event(conn: sqlite3.Connection, event: int, squad_ids: list[int]) -> int:
    """Real actual outcome, once the gameweek has finished. `player_stats_snapshot`
    is a live, single-row-per-player table (overwritten every sync) - its
    `event_points`/`minutes` only correctly reflect THIS event until the next
    gameweek's own matches start generating points, so this must be called
    promptly once a gameweek finishes (wired into the post-GW pipeline,
    which already runs at exactly that moment) rather than assumed always
    reconstructable later. Creates a prediction-less row when none exists
    (the honest GW1 state - this table didn't exist before its deadline) so
    the real outcome is still captured rather than silently dropped."""
    if not squad_ids:
        return 0
    season = current_season(conn)
    now = datetime.now(timezone.utc).isoformat()
    written = 0
    for player_id in squad_ids:
        snapshot = conn.execute(
            "SELECT event_points, minutes FROM player_stats_snapshot WHERE player_id=? "
            "ORDER BY retrieved_at DESC LIMIT 1",
            (player_id,),
        ).fetchone()
        if snapshot is None:
            continue

        qual = conn.execute(
            "SELECT direction, signal, reason FROM player_fpl_implications "
            "WHERE player_id=? AND phase='FULL_TIME' ORDER BY created_at DESC LIMIT 1",
            (player_id,),
        ).fetchone()
        user = conn.execute(
            "SELECT sentiment, note FROM user_observations WHERE subject_type='player' AND subject_id=? "
            "ORDER BY created_at DESC LIMIT 1",
            (player_id,),
        ).fetchone()

        existing = conn.execute(
            "SELECT id FROM prediction_outcomes WHERE player_id=? AND event=? AND season=?",
            (player_id, event, season),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO prediction_outcomes (player_id, event, season, predicted_at, qualitative_direction, "
                "qualitative_signal, qualitative_reason, user_sentiment, user_note, actual_points, actual_minutes, "
                "outcome_recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (player_id, event, season, now,
                 qual["direction"] if qual else None, qual["signal"] if qual else None, qual["reason"] if qual else None,
                 user["sentiment"] if user else None, user["note"] if user else None,
                 snapshot["event_points"], snapshot["minutes"], now),
            )
        else:
            conn.execute(
                "UPDATE prediction_outcomes SET qualitative_direction=?, qualitative_signal=?, qualitative_reason=?, "
                "user_sentiment=?, user_note=?, actual_points=?, actual_minutes=?, outcome_recorded_at=? WHERE id=?",
                (qual["direction"] if qual else None, qual["signal"] if qual else None, qual["reason"] if qual else None,
                 user["sentiment"] if user else None, user["note"] if user else None,
                 snapshot["event_points"], snapshot["minutes"], now, existing["id"]),
            )
        written += 1
    if written:
        conn.commit()
    return written
