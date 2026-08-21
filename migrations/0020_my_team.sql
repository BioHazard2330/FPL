-- migrations/0020_my_team.sql
-- Real "my team" tracking, 2026-08-21 - the user gave a real FPL entry id
-- (public, no login required: /entry/{id}/, /entry/{id}/history/,
-- /entry/{id}/event/{gw}/picks/ are all read-only official FPL API endpoints,
-- the same Tier 1 source and the same fetch_entry_picks() adapter method
-- already used for Plan 1c's EO sampling - not a new source, not the
-- previously-declined "FPL account login" scope, since nothing here
-- authenticates or writes back to the account). Lets the dashboard and
-- `fpl my-team` show the user's REAL squad/rank/history instead of only
-- ever showing squads this project itself built.

CREATE TABLE my_team_entry (
    entry_id INTEGER PRIMARY KEY,
    manager_name TEXT,
    region_name TEXT,
    favourite_team_id INTEGER,
    joined_time TEXT,
    started_event INTEGER,
    retrieved_at TEXT NOT NULL
);

-- Past-season summaries from entry/{id}/history/'s "past" array - real,
-- available immediately (no GW lock needed, these are closed seasons).
CREATE TABLE my_team_season_history (
    entry_id INTEGER NOT NULL REFERENCES my_team_entry(entry_id),
    season_name TEXT NOT NULL,
    total_points INTEGER,
    rank INTEGER,
    rank_percentage TEXT,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (entry_id, season_name)
);

-- Per-gameweek summaries for the LIVE season, from history/'s "current" array
-- (populates GW by GW as the season plays out) - separate from my_team_picks
-- below (which needs the individual GW to have locked; this "current" array
-- is keyed by whatever gameweeks the entry has actually played so far).
CREATE TABLE my_team_gw_summary (
    entry_id INTEGER NOT NULL,
    event INTEGER NOT NULL,
    points INTEGER,
    total_points INTEGER,
    overall_rank INTEGER,
    bank_tenths INTEGER,
    team_value_tenths INTEGER,
    event_transfers INTEGER,
    event_transfers_cost INTEGER,
    points_on_bench INTEGER,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (entry_id, event)
);

-- Real picks for one locked gameweek - current-state per event (delete+
-- insert per (entry_id, event) on re-sync, same category as
-- predicted_lineup_players: a squad snapshot, not an append-only history;
-- the my_team_gw_summary row above already carries the historical points).
CREATE TABLE my_team_picks (
    entry_id INTEGER NOT NULL,
    event INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    squad_slot INTEGER,       -- 1-15, FPL's own pick order (1-11 starters, 12-15 bench)
    multiplier INTEGER,       -- 0 (benched-and-not-subbed), 1, 2 (captain), 3 (triple captain)
    is_captain INTEGER NOT NULL DEFAULT 0,
    is_vice_captain INTEGER NOT NULL DEFAULT 0,
    active_chip TEXT,         -- chip played this GW, if any ('wildcard'/'freehit'/'bboost'/'3xc'), else NULL
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (entry_id, event, player_id)
);
CREATE INDEX idx_my_team_picks_event ON my_team_picks(entry_id, event);
