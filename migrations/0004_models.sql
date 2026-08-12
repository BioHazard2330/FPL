CREATE TABLE team_strength_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL REFERENCES teams(id),
    strength_overall_home INTEGER,
    strength_overall_away INTEGER,
    strength_attack_home INTEGER,
    strength_attack_away INTEGER,
    strength_defence_home INTEGER,
    strength_defence_away INTEGER,
    valid_from TEXT NOT NULL,
    valid_until TEXT
);
CREATE INDEX idx_team_strength_history_team ON team_strength_history(team_id, valid_from);

CREATE TABLE player_season_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    season_name TEXT NOT NULL,
    minutes INTEGER,
    starts INTEGER,
    total_points INTEGER,
    goals_scored INTEGER,
    assists INTEGER,
    clean_sheets INTEGER,
    goals_conceded INTEGER,
    bonus INTEGER,
    bps INTEGER,
    expected_goals REAL,
    expected_assists REAL,
    expected_goal_involvements REAL,
    expected_goals_conceded REAL,
    defensive_contribution INTEGER,
    start_cost INTEGER,
    end_cost INTEGER,
    retrieved_at TEXT NOT NULL,
    UNIQUE(player_id, season_name)
);
CREATE INDEX idx_season_history_player ON player_season_history(player_id);
