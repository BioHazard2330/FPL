-- The manager's own eye: a quick rating and tags for a player after watching a gameweek, kept per player and gameweek
-- (the latest save wins), so it can sit beside the data, feed the plan's eye gate, and be scored against what followed.
CREATE TABLE IF NOT EXISTS eye_note (
    player_id INTEGER NOT NULL,
    event INTEGER NOT NULL,
    rating INTEGER NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    note TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (player_id, event)
);
