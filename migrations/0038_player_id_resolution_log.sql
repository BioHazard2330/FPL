-- migrations/0038_player_id_resolution_log.sql
-- Real, persistent audit trail for historical player-identity repair
-- (2026-09-07, Phase 7.4 Part 2 - "for every repaired mapping record:
-- player/FPL ID/Understat ID/season(s)/resolution method/confidence/
-- source"). `player_name_aliases` (migration 0009) already IS the real,
-- trusted (source, source_name) -> player_id mapping this project reuses
-- on every subsequent lookup - this table does NOT duplicate it. It adds
-- what that cache table structurally cannot carry: WHICH method actually
-- resolved a given historical row (exact match vs the team-scoped fuzzy
-- fallback), a real confidence label, and the specific season(s)/understat
-- ids a repair pass touched - so a repaired mapping is auditable after the
-- fact, not just silently applied.

CREATE TABLE player_id_resolution_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    understat_player_id TEXT NOT NULL,
    season TEXT NOT NULL,              -- dash form, e.g. "2023-24" - the real season this repair touched
    source_name TEXT NOT NULL,         -- the real raw name Understat reported for this understat_player_id
    resolution_method TEXT NOT NULL,   -- "exact_match" | "team_scoped_fuzzy"
    confidence TEXT NOT NULL,          -- "high" (exact) | "medium" (fuzzy)
    resolved_at TEXT NOT NULL,
    UNIQUE(player_id, understat_player_id, season)
);
CREATE INDEX idx_player_id_resolution_log_player ON player_id_resolution_log(player_id);
CREATE INDEX idx_player_id_resolution_log_season ON player_id_resolution_log(season);
