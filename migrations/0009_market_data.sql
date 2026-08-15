-- migrations/0009_market_data.sql
-- Pillar 0 (prediction-accuracy core, spec 2026-08-15-market-rivaling-architecture-design.md):
-- new Tier-2 model-input sources (historical results+odds, shot-level xG/xA) and the
-- team/player identity crosswalk needed because external sources use free-text names,
-- not FPL's per-season internal ids (promoted/relegated teams aren't in `teams` at all).

CREATE TABLE market_teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL UNIQUE,
    fpl_team_id INTEGER REFERENCES teams(id)
);

CREATE TABLE team_name_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_team_id INTEGER NOT NULL REFERENCES market_teams(id),
    source TEXT NOT NULL,
    source_name TEXT NOT NULL,
    UNIQUE(source, source_name)
);

CREATE TABLE player_name_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    source TEXT NOT NULL,
    source_name TEXT NOT NULL,
    UNIQUE(source, source_name)
);

-- Historical + live match results (football-data.co.uk). Odds live in the sibling
-- table below, linked by match_id, since the same source row carries both.
CREATE TABLE match_results_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season TEXT NOT NULL,
    match_date TEXT NOT NULL,
    home_team_id INTEGER NOT NULL REFERENCES market_teams(id),
    away_team_id INTEGER NOT NULL REFERENCES market_teams(id),
    home_goals INTEGER NOT NULL,
    away_goals INTEGER NOT NULL,
    source TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    UNIQUE(season, match_date, home_team_id, away_team_id)
);
CREATE INDEX idx_match_results_season ON match_results_history(season, match_date);

CREATE TABLE team_match_odds_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES match_results_history(id),
    source TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    home_win_odds REAL,
    draw_odds REAL,
    away_win_odds REAL,
    over_2_5_odds REAL,
    under_2_5_odds REAL,
    retrieved_at TEXT NOT NULL,
    UNIQUE(match_id, source, bookmaker)
);

-- Shot-level per-match player stats (Understat). Deliberately not FK'd to
-- match_results_history - cross-source match linking by fuzzy date/name would
-- be brittle; team-level xG is aggregated independently via market_team_id
-- instead of joining match-to-match across sources.
CREATE TABLE player_match_stats_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    understat_match_id TEXT NOT NULL,
    understat_player_id TEXT NOT NULL,
    player_id INTEGER REFERENCES players(id),
    market_team_id INTEGER NOT NULL REFERENCES market_teams(id),
    season TEXT NOT NULL,
    match_date TEXT NOT NULL,
    minutes INTEGER NOT NULL,
    goals INTEGER NOT NULL,
    assists INTEGER NOT NULL,
    shots INTEGER NOT NULL,
    xg REAL NOT NULL,
    xa REAL NOT NULL,
    key_passes INTEGER NOT NULL,
    yellow_cards INTEGER NOT NULL,
    red_cards INTEGER NOT NULL,
    retrieved_at TEXT NOT NULL,
    UNIQUE(understat_match_id, understat_player_id)
);
CREATE INDEX idx_player_match_stats_player ON player_match_stats_history(player_id, season, match_date);
CREATE INDEX idx_player_match_stats_team ON player_match_stats_history(market_team_id, season, match_date);

CREATE TABLE model_backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_version TEXT NOT NULL,
    season TEXT NOT NULL,
    rounds_evaluated INTEGER NOT NULL,
    predictions_scored INTEGER NOT NULL,
    mae REAL NOT NULL,
    rmse REAL NOT NULL,
    baseline_mae REAL NOT NULL,
    git_commit TEXT,
    run_at TEXT NOT NULL
);
CREATE INDEX idx_backtest_runs_version ON model_backtest_runs(model_version, season);
