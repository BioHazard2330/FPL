-- What people who watched said: BBC Sport's player ratings for a match (the reporter's score and one-line verdict, and the
-- average of the fans' scores, with Player of the Match), one row per player and fixture; and the articles already read.
CREATE TABLE IF NOT EXISTS watcher_rating (
    fixture_id INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    reporter_rating REAL,
    reporter_note TEXT,
    fan_rating REAL,
    potm INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    link TEXT NOT NULL,
    published_at TEXT,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (fixture_id, player_id)
);
CREATE TABLE IF NOT EXISTS watcher_article (
    link TEXT PRIMARY KEY,
    fixture_id INTEGER,
    players INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    retrieved_at TEXT NOT NULL
);
