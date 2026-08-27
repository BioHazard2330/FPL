-- migrations/0033_solio_projections.sql
-- Solio Analytics independent-model benchmark (public, no-auth
-- https://fpl.solioanalytics.com/api/data/latest.json). One row per player
-- per snapshot, merged across whichever of Solio's own top-N category lists
-- (topProjected/topCaptains/topDifferentials/topGoals/topAssists/topBonus/
-- topDefCon/topTransfersIn/topTransfersOut) the player appeared in - Solio
-- publishes overlapping top-N lists, not one flat per-player table, so a
-- player can supply fields from several categories in the same snapshot.
-- `player_id`/`team_id` are nullable: Solio has no player_id of its own,
-- only free-text names/team codes, resolved via the existing
-- market_identity/predicted_lineups_source crosswalk - an unresolved name
-- is stored anyway (never dropped) so a match can be retried later.
CREATE TABLE solio_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gameweek INTEGER NOT NULL,
    generated_at TEXT NOT NULL,   -- Solio's own model-run timestamp (payload's generatedAt)
    deadline_iso TEXT,
    source_url TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,   -- our own fetch time
    raw_path TEXT                 -- path from ingestion.raw_store.save_raw, for audit/replay
);
CREATE INDEX idx_solio_snapshot_gw ON solio_snapshot(gameweek);

CREATE TABLE solio_player_projection (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES solio_snapshot(id),
    player_id INTEGER REFERENCES players(id),
    source_name TEXT NOT NULL,    -- Solio's raw display name, kept even once resolved
    team_short TEXT,
    position TEXT,
    price INTEGER,
    ownership REAL,
    pr_points REAL,               -- prPoints: Solio's total projected points
    captain_proj_points REAL,
    leverage REAL,                -- differential leverage (topDifferentials only)
    pr_goals REAL,
    pr_points_from_goals REAL,
    pr_assists REAL,
    pr_points_from_assists REAL,
    pr_bonus_points REAL,
    pr_defcon_prob REAL,
    pr_defcon_points REAL,
    transfers_in INTEGER,
    transfers_out INTEGER,
    categories TEXT NOT NULL,     -- comma-joined source categories this row was built from
    UNIQUE(snapshot_id, source_name)
);
CREATE INDEX idx_solio_player_projection_snapshot ON solio_player_projection(snapshot_id);
CREATE INDEX idx_solio_player_projection_player ON solio_player_projection(player_id);

CREATE TABLE solio_team_projection (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES solio_snapshot(id),
    team_id INTEGER REFERENCES teams(id),
    team_name TEXT NOT NULL,
    pr_goals_for REAL,
    pr_goals_against REAL,
    cs_prob REAL,
    categories TEXT NOT NULL,     -- 'bestCleanSheets' and/or 'bestAttackingFixtures'
    UNIQUE(snapshot_id, team_name)
);
CREATE INDEX idx_solio_team_projection_snapshot ON solio_team_projection(snapshot_id);
