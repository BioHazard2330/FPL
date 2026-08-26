-- migrations/0029_prediction_outcomes.sql
-- Calibration/learning persistent storage (2026-08-26, GW1-postmortem pass,
-- section R). Real, explicit scope boundary: this stores the raw
-- prediction-vs-outcome data future calibration would need - it does NOT
-- fit any statistical calibration model (one gameweek is not enough real
-- data to calibrate against honestly, same discipline this project already
-- applies everywhere else - price_forecast.py, squad_churn.py, etc). One
-- row per (player_id, event, season): the model's own prediction (captured
-- once, near the gameweek's deadline, via record_predictions_for_locked_squad),
-- the qualitative read and any real user observation recorded around that
-- gameweek, and the real actual outcome once it exists (via
-- record_outcomes_for_finished_event). Never overwritten once both sides are
-- filled - a genuine historical record, not a live-state table.
CREATE TABLE prediction_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    event INTEGER NOT NULL,
    season TEXT NOT NULL,
    predicted_median REAL,
    predicted_floor REAL,
    predicted_ceiling REAL,
    predicted_confidence TEXT,
    predicted_expected_minutes REAL,
    model_version TEXT,
    predicted_at TEXT NOT NULL,
    qualitative_direction TEXT,
    qualitative_signal TEXT,
    qualitative_reason TEXT,
    user_sentiment TEXT,
    user_note TEXT,
    actual_points INTEGER,
    actual_minutes INTEGER,
    outcome_recorded_at TEXT,
    UNIQUE(player_id, event, season)
);
CREATE INDEX idx_prediction_outcomes_event ON prediction_outcomes(event, season);
