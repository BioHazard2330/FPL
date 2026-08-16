-- migrations/0011_sample_ownership.sql
-- Pillar 1 Plan 1c (spec: 2026-08-16-decision-intelligence-plan1c-design.md): real
-- effective ownership (EO) needs captain/triple-captain multiplier data that raw
-- selected_by_percent doesn't carry. Sourced from a bounded, rank-stratified sample
-- of leagues-classic/314 (Overall) managers' entry/{id}/event/{gw}/picks/ - not a
-- single API field like price/ownership, so this is a point-in-time sample per
-- (player, event), not a valid_from/valid_until slowly-changing fact. FACTS only
-- (sums/counts) - models/effective_ownership.py derives percent + margin of error
-- on read, per CLAUDE.md's FACTS/DERIVED/REASONING layering rule.

CREATE TABLE player_sample_ownership_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    event INTEGER NOT NULL REFERENCES events(id),
    sample_size INTEGER NOT NULL,
    owned_count INTEGER NOT NULL,
    captained_count INTEGER NOT NULL,
    sum_multiplier INTEGER NOT NULL,
    sum_multiplier_sq INTEGER NOT NULL,
    retrieved_at TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_sample_ownership_player_event ON player_sample_ownership_history(player_id, event);
