-- Midweek watch: Premier League clubs' cup and European matches read from FotMob's match details
-- (ingestion/midweek_watch.py). One row per match and one per Premier League player who was in the
-- matchday squad or listed unavailable.
CREATE TABLE IF NOT EXISTS cup_match (
    fotmob_match_id TEXT PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id),
    competition TEXT,
    opponent_name TEXT,
    is_home INTEGER,
    kickoff_utc TEXT,
    status TEXT,
    home_score INTEGER,
    away_score INTEGER,
    live_minute TEXT,
    retrieved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cup_appearance (
    fotmob_match_id TEXT NOT NULL REFERENCES cup_match(fotmob_match_id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    team_id INTEGER NOT NULL,
    role TEXT NOT NULL,              -- STARTED / BENCH / UNAVAILABLE
    minutes INTEGER,
    sub_on_minute INTEGER,
    sub_off_minute INTEGER,
    goals INTEGER,
    assists INTEGER,
    absent_kind TEXT,
    absent_return TEXT,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (fotmob_match_id, player_id)
);

CREATE INDEX IF NOT EXISTS idx_cup_appearance_player ON cup_appearance(player_id);
