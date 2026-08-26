-- Real per-player anytime-goalscorer odds (dashboard-overhaul pass, 2026-08-22).
-- Current-state per fixture (delete+insert on refresh, same pattern as
-- predicted_lineup_players/player_start_probability) - a stale odds snapshot has
-- no standing value once a fresher one exists. Raw implied probability only
-- (1/decimal_price) - NOT devigged: true devigging of an anytime-scorer market
-- needs the full market's overround share per player (a "no goalscorer"
-- residual isn't explicitly quoted), a genuinely different problem from the
-- simple 2/3-outcome devig this project already does for match-result odds.
-- Disclosed as raw, not silently presented as devigged.
CREATE TABLE player_odds_live (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fixture_id INTEGER NOT NULL REFERENCES fixtures(id),
    player_id INTEGER REFERENCES players(id),
    player_name_raw TEXT NOT NULL,
    source TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    anytime_scorer_price REAL NOT NULL,
    implied_probability_raw REAL NOT NULL,
    retrieved_at TEXT NOT NULL
);
CREATE INDEX idx_player_odds_live_fixture ON player_odds_live(fixture_id);
