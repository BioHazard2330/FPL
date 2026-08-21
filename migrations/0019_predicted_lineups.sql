-- migrations/0019_predicted_lineups.sql
-- Closes CLAUDE.md's documented "predicted lineups (section 47) - no reliable
-- free source found" gap. Found 2026-08-21: fantasyfootballscout.co.uk/team-news/
-- is real, free, no login, no paywall (verified live), robots.txt has zero
-- disallow rules for any user-agent, and the predicted-XI/injury data is
-- server-rendered static HTML (no JS rendering needed). Second, genuinely
-- gated sources (fpl.team - paywalled beyond 2 teams; fplreview.com - 403s)
-- were checked and rejected rather than scraped around.
--
-- CURRENT-STATE facts, not an append-only history like news_items: a
-- predicted lineup is only meaningful as "the latest read before this
-- deadline" - yesterday's predicted XI has no standing value once today's
-- news changes it, so unlike news_items (Data model Phase 6/Pillar 2) this
-- table is refreshed in place (delete+insert per sync), matching the
-- players/fixtures "current-state facts" category from Data model Phase 2,
-- not the valid_from/valid_until slowly-changing-fact pattern.

CREATE TABLE predicted_lineup_teams (
    team_id INTEGER PRIMARY KEY REFERENCES teams(id),
    formation TEXT,
    next_match_text TEXT,
    latest_news TEXT,
    source TEXT NOT NULL,
    source_tier TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE predicted_lineup_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL REFERENCES teams(id),
    player_id INTEGER REFERENCES players(id),
    player_name_raw TEXT NOT NULL,
    predicted_status TEXT NOT NULL,  -- 'starting' | 'bench' | 'out' | 'doubt' | 'banned'
    lineup_row INTEGER,              -- formation row (1=GK, 2=DEF, ...) for 'starting' only, else NULL
    doubt_percent INTEGER,           -- fitness % for 'doubt' rows when the source publishes one, else NULL
    fetched_at TEXT NOT NULL
);
CREATE INDEX idx_predicted_lineup_players_team ON predicted_lineup_players(team_id);
CREATE INDEX idx_predicted_lineup_players_player ON predicted_lineup_players(player_id);
