-- migrations/0039_historical_archive_recovery.sql
-- Phase 7.5 Part 3/4/5/7 - real structural historical-data recovery from a
-- free, MIT-licensed, community-maintained public archive
-- (github.com/vaastav/Fantasy-Premier-League). Confirmed live 2026-09-07:
-- FPL's own numeric `players.id` is NOT stable across seasons (Bruno
-- Fernandes is id=426 today, id=277 in the archive's 2021-22 snapshot) -
-- `players.code` IS the real, stable cross-season key, so every table below
-- is keyed by `player_code`, never `player_id` - resolution to this
-- project's own CURRENT `players.id` happens at query time via a
-- `players.code` join, never stored redundantly here (keeps the archive
-- data source-pure and re-derivable, same posture as every other real
-- source table in this project).

-- Real per-gameweek historical price/ownership/transfer-momentum snapshot -
-- Phase 7.4 Part 3's own disclosed gap ("no historical weekly price data
-- exists anywhere in this project"). `price_tenths`/`selected_count` are
-- the value AS OF that real historical gameweek deadline (the archive's own
-- `value`/`selected` fields) - inherently temporally correct for a
-- walk-forward backtest cutoff, never an end-of-season or current
-- reconstruction.
CREATE TABLE historical_gw_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_code INTEGER NOT NULL,
    season TEXT NOT NULL,          -- dash form, e.g. "2023-24"
    gw INTEGER NOT NULL,
    price_tenths INTEGER NOT NULL,
    selected_count INTEGER,        -- real raw ownership count that GW (not a %; no reliable total-managers denominator per historical GW)
    transfers_in INTEGER,
    transfers_out INTEGER,
    team_short_name TEXT NOT NULL, -- real historical team affiliation for THIS season/GW - see Part 4
    source TEXT NOT NULL DEFAULT 'vaastav_fpl_archive',
    retrieved_at TEXT NOT NULL,
    UNIQUE(player_code, season, gw)
);
CREATE INDEX idx_historical_gw_snapshot_code_season ON historical_gw_snapshot(player_code, season);
CREATE INDEX idx_historical_gw_snapshot_season_gw ON historical_gw_snapshot(season, gw);

-- Real full historical roster per season (includes players who have since
-- left the live FPL API entirely - this project's own `players` table only
-- ever holds the CURRENT live roster, confirmed live: 0 rows with
-- `removed=1` despite 5 real backtestable past seasons). This is the real
-- fix for "no historical team-affiliation table anywhere in this project's
-- schema" (`data_fidelity.py`'s own disclosed gap) AND for player-seasons
-- that are structurally invisible to `player_season_history` because the
-- player is no longer in the live `players` table to anchor a `player_id`
-- to at all.
CREATE TABLE historical_player_roster (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_code INTEGER NOT NULL,
    season TEXT NOT NULL,
    season_fpl_id INTEGER NOT NULL,  -- that season's own (unstable) FPL element id - real, disclosed, never used as a cross-season key
    team_short_name TEXT NOT NULL,
    position TEXT NOT NULL,          -- GKP/DEF/MID/FWD, real element_type mapping
    web_name TEXT NOT NULL,
    first_name TEXT NOT NULL,
    second_name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'vaastav_fpl_archive',
    retrieved_at TEXT NOT NULL,
    UNIQUE(player_code, season)
);
CREATE INDEX idx_historical_player_roster_code ON historical_player_roster(player_code);
CREATE INDEX idx_historical_player_roster_season ON historical_player_roster(season);

-- Real, independent, community-maintained Understat<->FPL identity
-- crosswalk (the archive's own `id_dict.csv`) - a real, SECOND resolution
-- signal used to cross-validate/supplement this project's own resolver on
-- historical seasons (Phase 7.5 Part 5/6), never blindly substituted for it
-- without disclosure (see `historical_archive_source.py`'s own module
-- docstring for the real adoption decision).
CREATE TABLE historical_identity_crosswalk (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    understat_player_id TEXT NOT NULL,
    player_code INTEGER NOT NULL,
    season TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'vaastav_fpl_archive',
    retrieved_at TEXT NOT NULL,
    UNIQUE(understat_player_id, season)
);
CREATE INDEX idx_historical_identity_crosswalk_code ON historical_identity_crosswalk(player_code, season);

-- Real, compact, per-(season, field, source) INGESTION-EVENT lineage
-- (Phase 7.5 Part 7 - "a compact lineage table is enough", explicitly NOT a
-- per-row metadata payload). One row per real ingestion run, not one row
-- per recovered data row - `historical backtest result -> underlying data
-- -> source -> resolution/transformation` stays auditable by joining a
-- data table's own `season`/`source` columns back to this table, without
-- bloating every runtime object.
CREATE TABLE historical_data_lineage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season TEXT NOT NULL,
    field TEXT NOT NULL,             -- e.g. "gw_snapshot" | "player_roster" | "identity_crosswalk"
    source TEXT NOT NULL,
    source_identifier TEXT NOT NULL, -- real commit sha / file path this run actually fetched, for reproducibility
    retrieved_at TEXT NOT NULL,
    transformation TEXT NOT NULL,    -- one-line real, disclosed description of any parsing/normalization applied
    confidence TEXT NOT NULL,        -- data_fidelity.py's own CONFIDENCE_* vocabulary
    row_count INTEGER NOT NULL
);
CREATE INDEX idx_historical_data_lineage_season_field ON historical_data_lineage(season, field);
