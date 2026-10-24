CREATE TABLE IF NOT EXISTS match_unavailable (
    match_id INTEGER NOT NULL REFERENCES match_intelligence(id),
    fotmob_player_id TEXT NOT NULL,
    player_id INTEGER REFERENCES players(id),
    team_id INTEGER REFERENCES teams(id),
    name_raw TEXT,
    kind TEXT,
    expected_return TEXT,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (match_id, fotmob_player_id)
);
CREATE INDEX IF NOT EXISTS idx_match_unavailable_player ON match_unavailable(player_id);

CREATE TABLE IF NOT EXISTS match_coach (
    match_id INTEGER NOT NULL REFERENCES match_intelligence(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    coach_name TEXT,
    formation TEXT,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (match_id, team_id)
);
