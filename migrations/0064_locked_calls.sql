-- A decision the manager has settled for a gameweek. It stays settled until a tripwire reopens it or a new call replaces it.
CREATE TABLE IF NOT EXISTS locked_call (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event INTEGER NOT NULL,
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    detail TEXT NOT NULL,
    locked_at TEXT NOT NULL,
    released_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_locked_call_event ON locked_call(event, kind);
