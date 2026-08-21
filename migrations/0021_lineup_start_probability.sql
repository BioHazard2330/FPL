-- migrations/0021_lineup_start_probability.sql
-- Real per-player start-PERCENTAGE predicted lineups (2026-08-21), a richer
-- Tier 2-4 source than migration 0019's binary starting/bench/doubt flag -
-- see ingestion/lineup_probability_source.py's module docstring for the
-- real evidence (fantasyfootballpundit.com, free, no login, real server-
-- rendered "Start %" per player). Current-state, not append-only history -
-- a stale percentage has no standing value once a fresher one exists, same
-- reasoning predicted_lineup_players (migration 0019) already uses.

CREATE TABLE player_start_probability (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    position_raw TEXT,          -- the site's own position label (e.g. "RM", "DCM") - reference only, not authoritative
    start_percent INTEGER NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX idx_player_start_probability_team ON player_start_probability(team_id);
