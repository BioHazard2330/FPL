-- A qualitative view of one player for a run of gameweeks (a returning starter, a new role, a new manager), applied to the
-- projections every decision reads and scored afterwards against what he did.
CREATE TABLE IF NOT EXISTS pundit_view (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    factor REAL NOT NULL,
    from_event INTEGER NOT NULL,
    through_event INTEGER NOT NULL,
    reason TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'pundit',
    made_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_pundit_view_player ON pundit_view(player_id);
