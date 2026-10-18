-- migrations/0048_live_forecast_log.sql
-- Every live forecast the server produces, so a gameweek's forecasts can be scored
-- against the points it actually ended on. Facts about what was forecast, when.
CREATE TABLE live_forecast_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event INTEGER NOT NULL,
    logged_at INTEGER NOT NULL,
    now_points REAL NOT NULL,
    mean REAL NOT NULL,
    p10 REAL NOT NULL,
    p50 REAL NOT NULL,
    p90 REAL NOT NULL,
    field_now REAL,
    field_mean REAL,
    fixtures_left INTEGER NOT NULL,
    fixtures_live INTEGER NOT NULL
);
CREATE INDEX idx_live_forecast_log_event ON live_forecast_log(event, logged_at);
