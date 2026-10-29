-- The overall-league total at a few target ranks (1k, 10k, 100k), read from FPL's public overall standings after each
-- sync, so the distance to a rank target and the pace at which that target moves are both measured, not guessed.
CREATE TABLE IF NOT EXISTS rank_threshold (
    season TEXT NOT NULL,
    event INTEGER NOT NULL,
    rank_target INTEGER NOT NULL,
    total INTEGER NOT NULL,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (season, event, rank_target)
);
