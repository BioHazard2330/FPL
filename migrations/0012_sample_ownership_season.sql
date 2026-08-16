-- migrations/0012_sample_ownership_season.sql
-- 0011 keyed player_sample_ownership_history on (player_id, event) alone. events.id is
-- 1-38 and re-upserted by id every season, and FPL reassigns `element` (player) ids
-- between seasons - so next season's GW1 sample would either be skipped by the
-- idempotency COUNT(*) (rows already "exist" for event 1) or silently mixed with the
-- previous season's rows, and get_all_sample_eo's MAX(event) resolution could hand a
-- stale season's numbers to the new season's players labelled eo_source="sampled".
-- Every comparable table here is season-scoped already (player_season_history.season_name,
-- rules.season, the 0009 market-data tables); this brings sampled EO in line, using the
-- same "YYYY-YY" string convention (rules.season / models.rules.current_season).
--
-- The DEFAULT below only exists because SQLite requires one for a NOT NULL ADD COLUMN.
-- No production rows exist in this table anywhere (confirmed preseason 2026-08-16 - GW1
-- had not locked, so no sampling run has ever succeeded), so nothing real hits it.

ALTER TABLE player_sample_ownership_history ADD COLUMN season TEXT NOT NULL DEFAULT 'unknown';

DROP INDEX idx_sample_ownership_player_event;
CREATE UNIQUE INDEX idx_sample_ownership_player_event_season
    ON player_sample_ownership_history(player_id, event, season);
