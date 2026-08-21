-- migrations/0025_match_events.sql
-- Real live match incident feed (Pillar 4, live-match-feed pass, 2026-08-21).
-- Deliberately separate from match_observations (Slice A2's LLM-authored
-- OBSERVED/INFERRED/FPL_IMPLICATION layer) - this table is RAW EVIDENCE
-- only, real structured incidents straight from FotMob (Goal/Card/Sub/Shot/
-- VAR/Injury), never LLM-authored text, never mixed with qualitative
-- analysis. The qualitative engine can consume this evidence later; this
-- table exists so the dashboard's live match feed has a real, provenance-
-- carrying, append-only source to read instead of re-deriving it from
-- player_match_state on every render.
--
-- UNIQUE(match_id, source, source_event_id) is the real idempotency key -
-- a re-poll of the same match re-inserts the exact same events with the
-- exact same source_event_id (FotMob's own eventId for match-fact events,
-- or its own shot id for shotmap-derived shot events) - INSERT OR IGNORE
-- means a duplicate poll never creates a duplicate feed row.
CREATE TABLE match_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES match_intelligence(id),
    source TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    minute INTEGER,
    event_type TEXT NOT NULL,
    team_id INTEGER REFERENCES teams(id),
    player_id INTEGER REFERENCES players(id),
    description TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    UNIQUE(match_id, source, source_event_id)
);
CREATE INDEX idx_match_events_match_minute ON match_events(match_id, minute);
