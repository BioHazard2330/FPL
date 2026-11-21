-- Every player's full FotMob match record (passes, duels, defensive actions, corners, physical...) and where he
-- lined up (the formation grid: depth x, width y), read once a match is finished (`ingestion/match_detail.py`).
CREATE TABLE player_match_detail (
    match_id INTEGER NOT NULL REFERENCES match_intelligence(id),
    fotmob_player_id INTEGER NOT NULL,
    player_id INTEGER,
    team_id INTEGER,
    started INTEGER NOT NULL,
    role TEXT,
    line_x REAL,
    line_y REAL,
    formation TEXT,
    stats_json TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (match_id, fotmob_player_id)
);
CREATE INDEX idx_player_match_detail_player ON player_match_detail(player_id);
CREATE INDEX idx_player_match_detail_team ON player_match_detail(team_id);
