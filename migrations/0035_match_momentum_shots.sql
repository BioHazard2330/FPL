-- migrations/0035_match_momentum_shots.sql
-- Real FotMob live-match-centre data (2026-08-29, "live command centre" pass)
-- - `content.momentum`/`content.shotmap` were confirmed present in the SAME
-- `matchDetails` payload `fotmob_source.py::sync_match` already fetches
-- every ~15-25s during a live match (live-tested against a real finished
-- GW2 match this session: 28 real shots with x/y/xG, a full per-minute
-- momentum series) but were never parsed or stored - this closes that gap
-- without any new network cost. `big_chances`/`big_chances_missed` extend
-- the existing `team_match_state` row the same way (real fields confirmed
-- present in the same "Top stats" group `_safe_team_stats` already reads).
ALTER TABLE team_match_state ADD COLUMN big_chances INTEGER;
ALTER TABLE team_match_state ADD COLUMN big_chances_missed INTEGER;

CREATE TABLE match_momentum (
    match_id INTEGER NOT NULL REFERENCES match_intelligence(id),
    minute INTEGER NOT NULL,
    value INTEGER NOT NULL,           -- FotMob's own real -100..100 scale, negative=away/positive=home
    source TEXT NOT NULL DEFAULT 'fotmob',
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (match_id, minute)
);

CREATE TABLE match_shots (
    match_id INTEGER NOT NULL REFERENCES match_intelligence(id),
    fotmob_shot_id TEXT NOT NULL,
    team_id INTEGER REFERENCES teams(id),
    player_id INTEGER REFERENCES players(id),
    fotmob_player_id TEXT,
    player_name TEXT,
    minute INTEGER,
    x REAL,                            -- real FotMob pitch-percentage coordinates (0-100), confirmed live
    y REAL,
    xg REAL,
    is_on_target INTEGER,
    outcome TEXT,                      -- Goal | AttemptSaved | Miss | BlockedShot | Post (FotMob's own real eventType)
    shot_type TEXT,
    situation TEXT,
    period TEXT,
    source TEXT NOT NULL DEFAULT 'fotmob',
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (match_id, fotmob_shot_id)
);
CREATE INDEX idx_match_shots_match ON match_shots(match_id, minute);
