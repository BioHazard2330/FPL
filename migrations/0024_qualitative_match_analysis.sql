-- migrations/0024_qualitative_match_analysis.sql
-- Qualitative Match Analysis + post-match pipeline (Pillar 4, Slice A2). See
-- docs/superpowers/specs/2026-08-21-qualitative-match-analysis-design.md.
-- Extends Slice A's match_observations/player_fpl_implications rather than
-- duplicating them - only phase/evidence/versioning columns are new.

ALTER TABLE match_observations ADD COLUMN phase TEXT NOT NULL DEFAULT 'FULL_TIME';
ALTER TABLE match_observations ADD COLUMN evidence_ref TEXT;
ALTER TABLE match_observations ADD COLUMN analysis_version TEXT;

ALTER TABLE player_fpl_implications ADD COLUMN phase TEXT NOT NULL DEFAULT 'FULL_TIME';
ALTER TABLE player_fpl_implications ADD COLUMN evidence_ref TEXT;
ALTER TABLE player_fpl_implications ADD COLUMN analysis_version TEXT;

-- Current-state upsert, one row per player - written ONLY on a FULL_TIME-
-- phase analysis (enforced in ingestion/qualitative_analysis.py, not just by
-- convention: a halftime read must never overwrite this).
CREATE TABLE player_qualitative_state (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    match_id INTEGER NOT NULL REFERENCES match_intelligence(id),
    role TEXT,
    tactical_signal TEXT,
    fpl_outlook TEXT,
    confidence TEXT NOT NULL DEFAULT 'low',
    evidence_ref TEXT,
    analysis_version TEXT,
    generated_at TEXT NOT NULL
);

CREATE TABLE team_qualitative_state (
    team_id INTEGER PRIMARY KEY REFERENCES teams(id),
    match_id INTEGER NOT NULL REFERENCES match_intelligence(id),
    tactical_signal TEXT,
    attacking_signal TEXT,
    defensive_signal TEXT,
    key_observation TEXT,
    fpl_implication TEXT,
    confidence TEXT NOT NULL DEFAULT 'low',
    evidence_ref TEXT,
    analysis_version TEXT,
    generated_at TEXT NOT NULL
);

-- One row per (match_id, phase) - a HALFTIME summary lives at its own key
-- and is never overwritten by/never overwrites the FULL_TIME one. This is
-- what makes halftime analysis genuinely provisional rather than a draft of
-- the final row.
CREATE TABLE match_analysis_summary (
    match_id INTEGER NOT NULL REFERENCES match_intelligence(id),
    phase TEXT NOT NULL,
    headline TEXT,
    uncertainties TEXT,
    analysis_version TEXT,
    generated_at TEXT NOT NULL,
    PRIMARY KEY (match_id, phase)
);

-- Append-only, real human input, never merged into AI-authored rows above -
-- the seed of the future "My Football View" system (deliberately not built
-- further than plain storage this cycle).
CREATE TABLE user_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER REFERENCES match_intelligence(id),
    subject_type TEXT NOT NULL,   -- player | team
    subject_id INTEGER NOT NULL,
    phase TEXT,
    sentiment TEXT,                -- positive | negative | neutral
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_user_observations_subject ON user_observations(subject_type, subject_id);
