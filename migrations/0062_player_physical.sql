-- Per player per match: minutes and FotMob's physical and touch figures, for league and cup matches alike
-- (ingestion/workload.py). The workload view sums them over the last 7, 14 and 28 days.
CREATE TABLE IF NOT EXISTS player_physical (
    fotmob_match_id TEXT NOT NULL,
    player_id INTEGER NOT NULL REFERENCES players(id),
    competition TEXT,
    kickoff_utc TEXT,
    minutes INTEGER,
    distance_m REAL,
    running_m REAL,
    sprint_m REAL,
    sprints INTEGER,
    top_speed REAL,
    touches INTEGER,
    touches_box INTEGER,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (fotmob_match_id, player_id)
);

CREATE INDEX IF NOT EXISTS idx_player_physical_player ON player_physical(player_id, kickoff_utc);

CREATE TABLE IF NOT EXISTS physical_match_read (
    fotmob_match_id TEXT PRIMARY KEY,
    players INTEGER NOT NULL,
    retrieved_at TEXT NOT NULL
);
