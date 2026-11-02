-- Matchday conditions (ingestion/matchday_conditions.py): each upcoming fixture's ground, referee (with FotMob's career
-- figures for him) and the Open-Meteo forecast for the kickoff hour; and each club's home ground for the map.
CREATE TABLE IF NOT EXISTS fixture_conditions (
    fixture_id INTEGER PRIMARY KEY REFERENCES fixtures(id),
    fotmob_match_id TEXT,
    stadium TEXT,
    city TEXT,
    lat REAL,
    lon REAL,
    capacity INTEGER,
    referee TEXT,
    ref_matches INTEGER,
    ref_yellows_pm REAL,
    ref_yellows_avg REAL,
    ref_reds INTEGER,
    ref_penalties INTEGER,
    ref_fouls_pm REAL,
    forecast_temp REAL,
    forecast_precip REAL,
    forecast_precip_prob REAL,
    forecast_wind REAL,
    forecast_gust REAL,
    forecast_code INTEGER,
    forecast_at TEXT,
    retrieved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS team_venue (
    team_id INTEGER PRIMARY KEY REFERENCES teams(id),
    stadium TEXT,
    city TEXT,
    lat REAL,
    lon REAL,
    capacity INTEGER,
    retrieved_at TEXT NOT NULL
);
