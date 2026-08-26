-- migrations/0032_elite_manager_panel.sql
-- Historical, skill-selected Elite-manager panel (2026-08-26, GW1-postmortem
-- audit P1). Real, confirmed constraint checked live before this was built:
-- FPL's leagues-classic/314/standings/ endpoint is season-scoped to whatever
-- season is currently live - there is no way to retroactively fetch a PAST
-- season's final standings. This table is only ever meaningfully populated
-- by running the snapshot near a real season's end, for use as the
-- following season's real historical panel - see
-- ingestion/elite_panel.py's own module docstring for the full account.
CREATE TABLE elite_manager_panel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season TEXT NOT NULL,
    entry_id INTEGER NOT NULL,
    final_rank INTEGER,
    captured_at TEXT NOT NULL,
    UNIQUE(season, entry_id)
);
CREATE INDEX idx_elite_manager_panel_season ON elite_manager_panel(season);
