-- Live overall-rank estimation (2026-08-21, live-gameweek layer item 3).
-- FPL's official API never publishes a live overall rank during a
-- gameweek (confirmed by this project's own research - see
-- ingestion/live_rank_sample.py's module docstring for the real
-- methodology this is based on, not a guess). One row per sampled manager
-- per (event, season) - current-state, delete+insert per resample, same
-- reasoning predicted_lineup_players/player_start_probability already use:
-- a stale sample has no standing value once a fresher one exists. Season
-- column follows the same season-scoping lesson player_sample_ownership_
-- history already learned (migration 0012): events.id is 1-38 and
-- re-upserted every season, so an event-only key would collide across
-- seasons.
CREATE TABLE live_rank_sample (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event INTEGER NOT NULL,
    season TEXT NOT NULL,
    entry_id INTEGER NOT NULL,
    pre_gw_rank INTEGER NOT NULL,     -- real, exact: this manager's own rank position on the standings page sampled
    pre_gw_total INTEGER NOT NULL,    -- real cumulative season total BEFORE this event
    live_points REAL NOT NULL,        -- this project's own computed live points for this event (see estimate_squad_live_points)
    current_total REAL NOT NULL,      -- pre_gw_total + live_points
    sampled_at TEXT NOT NULL,
    UNIQUE(event, season, entry_id)
);
CREATE INDEX idx_live_rank_sample_event ON live_rank_sample(event, season);
