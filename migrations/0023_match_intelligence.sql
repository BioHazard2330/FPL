-- migrations/0023_match_intelligence.sql
-- Match Intelligence Core (Pillar 4, Slice A) - the first real football-
-- intelligence layer underneath the FPL-statistics optimizer. Source: FotMob
-- public JSON endpoints (see docs/superpowers/specs/
-- 2026-08-21-match-intelligence-core-design.md). Every table carries
-- source/retrieved_at/confidence provenance per this project's own Data
-- Integrity rule. Current-state upsert per match (latest state only, keyed
-- on match_id+player/team) - full tactical history is deliberately deferred
-- to a later slice (Tactical Memory), same "current-state, not append-only"
-- pattern predicted_lineup_players/player_start_probability already use.

CREATE TABLE match_intelligence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fotmob_match_id TEXT UNIQUE NOT NULL,
    fpl_fixture_id INTEGER REFERENCES fixtures(id),
    competition TEXT,
    kickoff_utc TEXT,
    home_team_id INTEGER REFERENCES teams(id),
    away_team_id INTEGER REFERENCES teams(id),
    status TEXT NOT NULL,          -- PRE_MATCH | LIVE | HALFTIME | FULL_TIME
    home_score INTEGER,
    away_score INTEGER,
    source TEXT NOT NULL DEFAULT 'fotmob',
    retrieved_at TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'high',
    data_quality TEXT,
    raw_source_reference TEXT
);

CREATE TABLE player_match_state (
    match_id INTEGER NOT NULL REFERENCES match_intelligence(id),
    player_id INTEGER REFERENCES players(id),
    fotmob_player_id TEXT,
    team_id INTEGER REFERENCES teams(id),
    started INTEGER,
    minutes INTEGER,
    position TEXT,
    rating REAL,
    goals INTEGER,
    assists INTEGER,
    shots INTEGER,
    key_passes INTEGER,
    xg REAL,
    xa REAL,
    touches_box INTEGER,
    substituted_on_minute INTEGER,
    substituted_off_minute INTEGER,
    source TEXT NOT NULL DEFAULT 'fotmob',
    retrieved_at TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'medium',
    PRIMARY KEY (match_id, fotmob_player_id)
);
CREATE INDEX idx_player_match_state_player ON player_match_state(player_id);

CREATE TABLE team_match_state (
    match_id INTEGER NOT NULL REFERENCES match_intelligence(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    formation TEXT,
    possession_pct REAL,
    shots INTEGER,
    shots_on_target INTEGER,
    xg REAL,
    corners INTEGER,
    source TEXT NOT NULL DEFAULT 'fotmob',
    retrieved_at TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'medium',
    PRIMARY KEY (match_id, team_id)
);

-- LLM-skill-authored (see spec section 8) - never populated by deterministic
-- code. observed is the only column code may ever write; inferred/fpl_* stay
-- NULL until the match-intelligence-analysis skill runs.
CREATE TABLE match_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES match_intelligence(id),
    subject_type TEXT NOT NULL,    -- player | team
    subject_id INTEGER NOT NULL,
    observation_type TEXT NOT NULL,
    observed TEXT NOT NULL,
    inferred TEXT,
    fpl_direction TEXT,            -- POSITIVE | NEUTRAL | NEGATIVE | WATCH
    fpl_signal TEXT,                -- ROLE | MINUTES | CREATION | GOAL_THREAT | TEAM_ATTACK | FIXTURES | TACTICAL_CHANGE | SET_PIECES
    fpl_reason TEXT,
    confidence TEXT NOT NULL DEFAULT 'low',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_match_observations_match ON match_observations(match_id);

-- Denormalized read surface for future optimizer consumption (B/C) - a flat
-- table, not a join over match_observations. Also LLM-skill-authored.
CREATE TABLE player_fpl_implications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES match_intelligence(id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    signal TEXT NOT NULL,
    direction TEXT NOT NULL,
    reason TEXT,
    confidence TEXT NOT NULL DEFAULT 'low',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_player_fpl_implications_player ON player_fpl_implications(player_id);
