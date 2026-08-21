-- migrations/0026_match_intelligence_live_minute.sql
-- Real live match clock (2026-08-21, live-match-feed pass) - FotMob's own
-- display string (e.g. "17'", "HT", "45+2'"), stored raw rather than parsed
-- into an int (added time has no single honest numeric form). Additive
-- column on the existing match_intelligence table (Slice A, migration
-- 0023) - never touches its existing rows' other fields. A separate
-- migration from 0025 (match_events) deliberately - 0025 had already been
-- applied to the real dev DB by the time this column was needed, and this
-- project's own standing rule is to never edit an applied migration.
ALTER TABLE match_intelligence ADD COLUMN live_minute TEXT;
