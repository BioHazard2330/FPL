-- migrations/0047_player_gw_stats.sql
-- Per-gameweek official stats for every player (event/{n}/live): minutes, the
-- scoring events, the expected-stat columns FPL publishes (xG, xA, xGC) and the
-- points that resulted. Facts only - the luck audit derives from these, and a
-- row is "FPL says this player did this in this gameweek". A double gameweek is
-- one row (FPL aggregates it); `fixtures` counts how many matches it covers.
CREATE TABLE player_gw_stats (
    player_id INTEGER NOT NULL REFERENCES players(id),
    event INTEGER NOT NULL,
    season TEXT NOT NULL,
    minutes INTEGER NOT NULL,
    starts INTEGER,
    goals INTEGER NOT NULL,
    assists INTEGER NOT NULL,
    clean_sheets INTEGER NOT NULL,
    goals_conceded INTEGER NOT NULL,
    own_goals INTEGER NOT NULL,
    penalties_missed INTEGER NOT NULL,
    penalties_saved INTEGER NOT NULL,
    yellow_cards INTEGER NOT NULL,
    red_cards INTEGER NOT NULL,
    saves INTEGER NOT NULL,
    bonus INTEGER NOT NULL,
    bps INTEGER,
    defensive_contribution INTEGER,
    xg REAL,
    xa REAL,
    xgc REAL,
    total_points INTEGER NOT NULL,
    fixtures INTEGER NOT NULL DEFAULT 1,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (player_id, event, season)
);
CREATE INDEX idx_player_gw_stats_event ON player_gw_stats (season, event);
