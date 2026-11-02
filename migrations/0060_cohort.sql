-- The cohort: managers sampled from FPL's overall league around a rank (ingestion/cohort.py), with their season's
-- per-gameweek history and picks, to set the manager's own decisions against theirs.
CREATE TABLE IF NOT EXISTS cohort_entry (
    entry_id INTEGER NOT NULL,
    cohort TEXT NOT NULL,
    rank_at_sample INTEGER,
    total_at_sample INTEGER,
    sampled_event INTEGER,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (entry_id, cohort)
);

CREATE TABLE IF NOT EXISTS cohort_gw (
    entry_id INTEGER NOT NULL,
    event INTEGER NOT NULL,
    points INTEGER,
    total INTEGER,
    overall_rank INTEGER,
    bench_points INTEGER,
    transfers INTEGER,
    transfer_cost INTEGER,
    value INTEGER,
    chip TEXT,
    captain_id INTEGER,
    captain_multiplier INTEGER,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (entry_id, event)
);

CREATE TABLE IF NOT EXISTS cohort_pick (
    entry_id INTEGER NOT NULL,
    event INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    multiplier INTEGER NOT NULL,
    PRIMARY KEY (entry_id, event, player_id)
);
