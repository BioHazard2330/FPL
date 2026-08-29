-- migrations/0036_live_player_state.sql
-- Real canonical live-player state (2026-08-29, "live architecture rebuild"
-- pass, milestone 1: event bus + fast engine). A real SUBSTITUTION event
-- (a squad player coming OFF) is a real fact this project previously threw
-- away the instant it was written to `player_match_state` - nothing
-- downstream ever read `substituted_off_minute` to conclude "this player's
-- FPL minutes are now final for this match". This table is the FAST
-- ENGINE's own real, versioned output - not a second copy of
-- `player_match_state` (that stays the raw per-match football record);
-- this is the derived "what does this mean for THIS player's live FPL
-- state right now" fact, updated in place by real event handlers.
CREATE TABLE live_player_state (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    match_id INTEGER REFERENCES match_intelligence(id),
    minutes_locked INTEGER NOT NULL DEFAULT 0,   -- 1 once a real SUBSTITUTION_OFF or MATCH_FINISHED event has been observed for this player this match - their minutes this match cannot increase further
    minutes_at_lock INTEGER,                      -- the real minutes value at the moment it locked
    last_event_type TEXT,                         -- the real event_type that produced this row's current state
    state_version INTEGER NOT NULL DEFAULT 1,     -- real monotonic counter, incremented on every real update
    updated_at TEXT NOT NULL
);
