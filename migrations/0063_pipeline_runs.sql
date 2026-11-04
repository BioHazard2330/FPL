-- What each background cycle did: its steps, how long each took, what failed. A cycle killed by the 10-minute task limit
-- leaves a journal file that the next cycle records as 'killed'.
CREATE TABLE IF NOT EXISTS pipeline_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    seconds REAL,
    status TEXT NOT NULL,
    gated INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    steps TEXT NOT NULL DEFAULT '[]'
);
