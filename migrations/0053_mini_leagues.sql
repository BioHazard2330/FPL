-- The manager's FPL classic leagues, their standings and the rivals' picks (public FPL endpoints, no login).
CREATE TABLE IF NOT EXISTS fpl_league (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    league_type TEXT,
    rank_count INTEGER,
    entry_rank INTEGER,
    entry_last_rank INTEGER,
    tracked INTEGER NOT NULL DEFAULT 0,
    retrieved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fpl_league_standing (
    league_id INTEGER NOT NULL,
    entry_id INTEGER NOT NULL,
    entry_name TEXT,
    player_name TEXT,
    rank INTEGER,
    last_rank INTEGER,
    total INTEGER,
    event_total INTEGER,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (league_id, entry_id)
);

CREATE TABLE IF NOT EXISTS rival_event (
    entry_id INTEGER NOT NULL,
    event INTEGER NOT NULL,
    active_chip TEXT,
    points INTEGER,
    total_points INTEGER,
    bank INTEGER,
    value INTEGER,
    event_transfers INTEGER,
    event_transfers_cost INTEGER,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (entry_id, event)
);

CREATE TABLE IF NOT EXISTS rival_pick (
    entry_id INTEGER NOT NULL,
    event INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    multiplier INTEGER NOT NULL,
    is_captain INTEGER NOT NULL,
    is_vice_captain INTEGER NOT NULL,
    PRIMARY KEY (entry_id, event, player_id)
);
