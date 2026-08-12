CREATE TABLE player_setpiece_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    penalties_order INTEGER,
    penalties_text TEXT,
    corners_order INTEGER,
    corners_text TEXT,
    direct_fk_order INTEGER,
    direct_fk_text TEXT,
    valid_from TEXT NOT NULL,
    valid_until TEXT
);
CREATE INDEX idx_setpiece_history_player ON player_setpiece_history(player_id, valid_from);

-- Generic change-detection engine, sections 36-37.
CREATE TABLE change_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    old_value TEXT,
    new_value TEXT,
    detected_at TEXT NOT NULL,
    sources TEXT NOT NULL,
    confidence TEXT NOT NULL,
    severity TEXT NOT NULL,
    fpl_impact TEXT,
    action_required INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_change_events_detected ON change_events(detected_at);
CREATE INDEX idx_change_events_entity ON change_events(entity, entity_id);
