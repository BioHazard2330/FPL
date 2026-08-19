-- migrations/0013_news_items.sql
-- Plan 2a (Pillar 2, spec 2026-08-20-pillar2-plan2a-tier2-news-connector-design.md):
-- first Tier 2-4 (strong-reporter) source. FACTS only - a news_items row is "this
-- article exists, says this, as of this time," never a classified status change.

CREATE TABLE news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_tier TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    link TEXT NOT NULL,
    summary TEXT,
    published_at TEXT,
    retrieved_at TEXT NOT NULL,
    UNIQUE(source, external_id)
);
CREATE INDEX idx_news_items_published ON news_items(published_at);

CREATE TABLE news_item_players (
    news_item_id INTEGER NOT NULL REFERENCES news_items(id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    PRIMARY KEY (news_item_id, player_id)
);
CREATE INDEX idx_news_item_players_player ON news_item_players(player_id);

CREATE TABLE news_item_teams (
    news_item_id INTEGER NOT NULL REFERENCES news_items(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    PRIMARY KEY (news_item_id, team_id)
);
CREATE INDEX idx_news_item_teams_team ON news_item_teams(team_id);
