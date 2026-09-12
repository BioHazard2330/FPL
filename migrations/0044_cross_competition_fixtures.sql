-- migrations/0044_cross_competition_fixtures.sql
-- Real gap found 2026-09-12 (direct user report: "this automation shit
-- needs to happen always... before matches after matches in between
-- international breaks, champions league, efl cup, fa cup... pl teams
-- play there too and they can rotate or injuries can happen"). Confirmed:
-- every match this project has ever tracked is Premier League only,
-- because discovery is keyed entirely off FPL's own `fixtures` table,
-- which structurally can never carry a non-PL match. This closes that
-- gap - real FotMob team-level fixture data (confirmed live: FotMob's own
-- public `teams` endpoint returns each team's FULL fixture list across
-- every competition it plays in, including Champions League/EFL Cup/FA
-- Cup/Club Friendlies), stored separately from `match_intelligence`
-- (which stays PL-fixture-anchored) since these matches have no real FPL
-- fixture row to attach to.

ALTER TABLE teams ADD COLUMN fotmob_id INTEGER;

CREATE TABLE team_other_competition_fixtures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL REFERENCES teams(id),
    fotmob_match_id TEXT NOT NULL,
    competition TEXT NOT NULL,
    opponent_name TEXT,
    is_home INTEGER,
    kickoff_utc TEXT,
    finished INTEGER NOT NULL DEFAULT 0,
    home_score INTEGER,
    away_score INTEGER,
    source TEXT NOT NULL DEFAULT 'fotmob',
    retrieved_at TEXT NOT NULL,
    UNIQUE(team_id, fotmob_match_id)
);

CREATE INDEX idx_team_other_competition_fixtures_team_kickoff
    ON team_other_competition_fixtures(team_id, kickoff_utc);
