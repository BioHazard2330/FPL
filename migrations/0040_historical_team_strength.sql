-- migrations/0040_historical_team_strength.sql
-- Phase 7.5 Part 4 - real historical team-context recovery. This project's
-- own `team_strength_history` table (despite its name) is confirmed live-
-- only: exactly 20 rows total, one static snapshot per current team, no
-- real history at all. FPL's own official historical strength ratings
-- (attack/defence, home/away) ARE available per season in the same free
-- archive used for price/roster recovery (`teams.csv`) - real numbers FPL
-- itself computed and published that season, not a derived estimate.
-- Separate migration from 0039 (never edit an applied migration).

CREATE TABLE historical_team_strength (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season TEXT NOT NULL,
    team_short_name TEXT NOT NULL,
    team_name TEXT NOT NULL,
    strength_overall_home INTEGER,
    strength_overall_away INTEGER,
    strength_attack_home INTEGER,
    strength_attack_away INTEGER,
    strength_defence_home INTEGER,
    strength_defence_away INTEGER,
    source TEXT NOT NULL DEFAULT 'vaastav_fpl_archive',
    retrieved_at TEXT NOT NULL,
    UNIQUE(season, team_short_name)
);
CREATE INDEX idx_historical_team_strength_season ON historical_team_strength(season);
