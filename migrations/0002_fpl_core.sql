CREATE TABLE teams (
    id INTEGER PRIMARY KEY,
    code INTEGER NOT NULL,
    name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    strength_overall_home INTEGER,
    strength_overall_away INTEGER,
    strength_attack_home INTEGER,
    strength_attack_away INTEGER,
    strength_defence_home INTEGER,
    strength_defence_away INTEGER,
    pulse_id INTEGER,
    updated_at TEXT NOT NULL
);

CREATE TABLE element_types (
    id INTEGER PRIMARY KEY,
    singular_name TEXT NOT NULL,
    singular_name_short TEXT NOT NULL,
    plural_name TEXT NOT NULL,
    squad_min_play INTEGER,
    squad_max_play INTEGER,
    updated_at TEXT NOT NULL
);

CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    deadline_time TEXT NOT NULL,
    deadline_time_epoch INTEGER NOT NULL,
    finished INTEGER NOT NULL,
    is_previous INTEGER NOT NULL,
    is_current INTEGER NOT NULL,
    is_next INTEGER NOT NULL,
    average_entry_score INTEGER,
    highest_score INTEGER,
    updated_at TEXT NOT NULL
);

CREATE TABLE players (
    id INTEGER PRIMARY KEY,
    code INTEGER NOT NULL,
    web_name TEXT NOT NULL,
    first_name TEXT,
    second_name TEXT,
    team_id INTEGER NOT NULL REFERENCES teams(id),
    element_type INTEGER NOT NULL REFERENCES element_types(id),
    squad_number INTEGER,
    status TEXT NOT NULL,
    news TEXT,
    news_added TEXT,
    opta_code TEXT,
    removed INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_players_team ON players(team_id);

CREATE TABLE player_price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    value_tenths INTEGER NOT NULL,
    valid_from TEXT NOT NULL,
    valid_until TEXT
);
CREATE INDEX idx_price_history_player ON player_price_history(player_id, valid_from);

CREATE TABLE player_ownership_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    selected_by_percent REAL NOT NULL,
    valid_from TEXT NOT NULL,
    valid_until TEXT
);
CREATE INDEX idx_ownership_history_player ON player_ownership_history(player_id, valid_from);

CREATE TABLE player_stats_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    retrieved_at TEXT NOT NULL,
    stats_hash TEXT NOT NULL,
    total_points INTEGER,
    event_points INTEGER,
    minutes INTEGER,
    goals_scored INTEGER,
    assists INTEGER,
    clean_sheets INTEGER,
    goals_conceded INTEGER,
    own_goals INTEGER,
    penalties_saved INTEGER,
    penalties_missed INTEGER,
    yellow_cards INTEGER,
    red_cards INTEGER,
    saves INTEGER,
    bonus INTEGER,
    bps INTEGER,
    starts INTEGER,
    expected_goals REAL,
    expected_assists REAL,
    expected_goal_involvements REAL,
    expected_goals_conceded REAL,
    defensive_contribution INTEGER,
    ict_index REAL,
    form REAL,
    points_per_game REAL,
    now_cost INTEGER,
    chance_of_playing_next_round INTEGER,
    chance_of_playing_this_round INTEGER
);
CREATE INDEX idx_stats_snapshot_player ON player_stats_snapshot(player_id, retrieved_at);

CREATE TABLE fixtures (
    id INTEGER PRIMARY KEY,
    code INTEGER NOT NULL,
    event INTEGER REFERENCES events(id),
    kickoff_time TEXT,
    team_h INTEGER NOT NULL REFERENCES teams(id),
    team_a INTEGER NOT NULL REFERENCES teams(id),
    team_h_score INTEGER,
    team_a_score INTEGER,
    team_h_difficulty INTEGER,
    team_a_difficulty INTEGER,
    finished INTEGER NOT NULL,
    started INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_fixtures_event ON fixtures(event);

-- Versioned rule engine, section 39. One row per rule_key per change (append-only).
CREATE TABLE rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_key TEXT NOT NULL,
    season TEXT NOT NULL,
    version INTEGER NOT NULL,
    effective_date TEXT NOT NULL,
    source TEXT NOT NULL,
    value TEXT NOT NULL,
    UNIQUE(rule_key, season, version)
);
CREATE INDEX idx_rules_key_season ON rules(rule_key, season);

CREATE TABLE source_health (
    source_name TEXT PRIMARY KEY,
    last_success TEXT,
    last_failure TEXT,
    last_error TEXT,
    latency_ms INTEGER,
    failure_count INTEGER NOT NULL DEFAULT 0,
    parser_version TEXT
);
