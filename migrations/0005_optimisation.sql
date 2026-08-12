CREATE TABLE chip_windows (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    number INTEGER NOT NULL,
    start_event INTEGER NOT NULL,
    stop_event INTEGER NOT NULL,
    chip_type TEXT NOT NULL,
    season TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_chip_windows_season ON chip_windows(season);
