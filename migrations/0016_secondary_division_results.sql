-- migrations/0016_secondary_division_results.sql
-- Championship (or other secondary-division) historical results, kept in a
-- SEPARATE table from match_results_history rather than a filtered column on
-- it - deliberately so the live calibrated-v2 Dixon-Coles fit
-- (team_strength_dc.py::load_matches_for_fitting, which scans
-- match_results_history unfiltered) cannot possibly ingest a cross-division
-- match by accident. See docs/superpowers/specs/2026-08-20-preseason-
-- calibration-design.md's Component B (promoted-team calibration).

CREATE TABLE secondary_division_match_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    division TEXT NOT NULL,
    season TEXT NOT NULL,
    match_date TEXT NOT NULL,
    home_team_id INTEGER NOT NULL REFERENCES market_teams(id),
    away_team_id INTEGER NOT NULL REFERENCES market_teams(id),
    home_goals INTEGER NOT NULL,
    away_goals INTEGER NOT NULL,
    source TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    UNIQUE(division, season, match_date, home_team_id, away_team_id)
);
CREATE INDEX idx_secondary_division_results_season ON secondary_division_match_results(division, season);
