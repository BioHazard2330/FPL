-- migrations/0015_cross_league_prior.sql
-- Cross-league prior for a genuinely new-to-English-top-flight signing
-- (spec docs/superpowers/specs/2026-08-20-preseason-calibration-design.md).
-- One row per player: their most recent season's per-90 rates in whichever
-- of Understat's other 5 top-league leagues they were found in, scaled by a
-- league-quality factor computed from real fetched data at backfill time -
-- not a trained cross-league model, a documented heuristic fallback tier
-- that sits before the pure positional-average prior, after the existing
-- Understat/season-history fallbacks have nothing for this player at all.

CREATE TABLE player_cross_league_prior (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    source_league TEXT NOT NULL,
    source_season TEXT NOT NULL,
    source_team_name TEXT NOT NULL,
    minutes INTEGER NOT NULL,
    goals_per90 REAL NOT NULL,
    assists_per90 REAL NOT NULL,
    xg_per90 REAL NOT NULL,
    xa_per90 REAL NOT NULL,
    league_quality_factor REAL NOT NULL,
    retrieved_at TEXT NOT NULL,
    UNIQUE(player_id)
);
