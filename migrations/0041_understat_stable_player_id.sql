-- migrations/0041_understat_stable_player_id.sql
-- Phase 7.5 Part 6 - real, confirmed bug found while cross-validating this
-- project's own Understat identity resolution against the free archive's
-- id_dict.csv crosswalk: the archive's "Understat_ID" is small and stable
-- (e.g. "62" for a real named player, matching understat.com/player/<id>
-- profile urls); this project's OWN `player_match_stats_history.
-- understat_player_id` is large (400,000+) and DIFFERENT for every single
-- match row of the SAME real player (confirmed live: player_id=1 in
-- 2021-22 has 24 real match rows, 24 DISTINCT understat_player_id values).
-- Root cause, confirmed via a real live fetch of a real match page
-- (understat.com/getMatchData/16463): each roster entry in Understat's own
-- JSON carries BOTH a per-match-appearance `id` (what this project has
-- been storing, e.g. "490837" for David de Gea in that one match) AND a
-- SEPARATE, real, stable `player_id` field (e.g. "546" for the same real
-- player, unchanged across every match) - `understat_source.py` has always
-- read the wrong one.

-- Additive, nullable, never mutates the existing `understat_player_id`
-- column or its real, already-working UNIQUE(understat_match_id,
-- understat_player_id) constraint - the existing column's real, if
-- confusingly named, per-match-roster-entry semantics are UNCHANGED and
-- still correctly disambiguate rows within one match. This is a genuinely
-- NEW, additional field, not a backward-incompatible rename - a full
-- backfill of every already-stored historical row is a real, separate,
-- bounded re-fetch task (same network cost the historical-identity-repair
-- pass already pays), not attempted inside this migration itself.
ALTER TABLE player_match_stats_history ADD COLUMN understat_stable_player_id TEXT;
CREATE INDEX idx_player_match_stats_history_stable_id ON player_match_stats_history(understat_stable_player_id);
