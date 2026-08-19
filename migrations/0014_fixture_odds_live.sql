-- migrations/0014_fixture_odds_live.sql
-- Live pre-match odds feed (spec 2026-08-20-live-odds-feed-design.md). Keyed
-- directly on fixtures.id (not match_results_history, which requires a played
-- match with goals) since an upcoming fixture needs a quote before it happens.

CREATE TABLE fixture_odds_live (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fixture_id INTEGER NOT NULL REFERENCES fixtures(id),
    source TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    home_win_odds REAL NOT NULL,
    draw_odds REAL NOT NULL,
    away_win_odds REAL NOT NULL,
    over_2_5_odds REAL,
    under_2_5_odds REAL,
    retrieved_at TEXT NOT NULL,
    UNIQUE(fixture_id, source, bookmaker)
);
CREATE INDEX idx_fixture_odds_live_fixture ON fixture_odds_live(fixture_id);
