-- The start-percentage feed is current-state only (a sync deletes and rewrites it), so there has never been a history to
-- check it against what players then did. A row is appended whenever a player's figure changes, or after a day without a
-- change, so every figure the model ever acted on can later be set against who started.
CREATE TABLE player_start_probability_history (
    player_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    start_percent INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (player_id, fetched_at)
);
CREATE INDEX idx_start_probability_history_time ON player_start_probability_history(fetched_at);
