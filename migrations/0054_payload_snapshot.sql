-- The last built JSON payload of each heavy screen, served at once while the live server rebuilds it in the background.
CREATE TABLE IF NOT EXISTS payload_snapshot (
    screen TEXT PRIMARY KEY,
    body TEXT NOT NULL,
    built_at TEXT NOT NULL,
    build_seconds REAL
);
