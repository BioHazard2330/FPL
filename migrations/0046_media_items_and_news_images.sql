-- migrations/0046_media_items_and_news_images.sql
-- The news desk (2026-10-16). Video and community posts are not articles:
-- they carry a thumbnail, an author and a kind, and are embedded rather than
-- summarised, so they get their own table beside news_items. FACTS only - a row
-- is "this channel/subreddit published this, at this time", never an
-- endorsement or a signal on its own.
ALTER TABLE news_items ADD COLUMN image_url TEXT;

CREATE TABLE media_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('video', 'post')),
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    link TEXT NOT NULL,
    author TEXT,
    channel TEXT,
    thumbnail_url TEXT,
    description TEXT,
    published_at TEXT,
    retrieved_at TEXT NOT NULL,
    UNIQUE (source, external_id)
);
CREATE INDEX idx_media_items_published ON media_items (published_at);

CREATE TABLE media_item_players (
    media_item_id INTEGER NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    PRIMARY KEY (media_item_id, player_id)
);
CREATE INDEX idx_media_item_players_player ON media_item_players (player_id);
