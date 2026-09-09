-- migrations/0042_match_insights_reviews_richer_stats.sql
-- Real, currently-unread fields confirmed live 2026-09-10 in the SAME
-- FotMob matchDetails payload fotmob_source.py::sync_match already fetches
-- (real Everton 2-2 Man Utd match, fotmob matchId 5795438) - no new network
-- cost, this closes a real gap between what the payload carries and what
-- this project parses.
--
-- `expectedGoalsOnTarget` (xGOT) is a genuine separate field from
-- `expectedGoals` per shot, confirmed present. `goalCrossedY`/`goalCrossedZ`
-- give a real goal-frame placement (horizontal position + real height in
-- metres, confirmed against 2 real on-target goals this match: 0.77m and
-- 0.24m, consistent with a 2.44m crossbar) for on-target shots specifically
-- - null for shots that never reached the goal line, never fabricated.
ALTER TABLE match_shots ADD COLUMN xgot REAL;
ALTER TABLE match_shots ADD COLUMN goal_crossed_y REAL;
ALTER TABLE match_shots ADD COLUMN goal_crossed_z REAL;

-- Real stat categories confirmed present in the same content.stats.Periods.
-- All.stats block `_safe_team_stats` already reads a subset of (exact
-- "title" strings verified: "Touches in opposition box", "Accurate passes",
-- "Tackles", "Interceptions", "Blocks", "Clearances", "Duels won", "Yellow
-- cards", "Red cards", "Distance covered", "Number of sprints") - fetched by
-- every sync already, simply never parsed past 7 of the real ~18 categories.
--
-- Real raw-value formats confirmed live (2026-09-10) before writing this,
-- not guessed: "Accurate passes" is a compound string ("361 (86%)") - split
-- into a real count and a real accuracy percentage, two genuine facts, not
-- one. "Distance covered" is a bare integer in METRES ("112473"), not km -
-- stored as-is, no invented unit conversion.
ALTER TABLE team_match_state ADD COLUMN touches_opp_box INTEGER;
ALTER TABLE team_match_state ADD COLUMN accurate_passes INTEGER;
ALTER TABLE team_match_state ADD COLUMN pass_accuracy_pct REAL;
ALTER TABLE team_match_state ADD COLUMN tackles INTEGER;
ALTER TABLE team_match_state ADD COLUMN interceptions INTEGER;
ALTER TABLE team_match_state ADD COLUMN blocks INTEGER;
ALTER TABLE team_match_state ADD COLUMN clearances INTEGER;
ALTER TABLE team_match_state ADD COLUMN duels_won INTEGER;
ALTER TABLE team_match_state ADD COLUMN yellow_cards INTEGER;
ALTER TABLE team_match_state ADD COLUMN red_cards INTEGER;
ALTER TABLE team_match_state ADD COLUMN distance_covered_m INTEGER;
ALTER TABLE team_match_state ADD COLUMN sprints INTEGER;

-- Real FotMob-authored storylines (content.insights[]) - e.g. "Everton have
-- scored 11 goals in their last 5 matches." Real editorial text FotMob
-- already writes and publishes, never LLM-authored or derived here.
-- `team_id` is nullable: a real insight can be player-scoped (`playerId`
-- set instead) or match-scoped (neither set) - stored honestly as whichever
-- it actually is, never forced onto a team.
CREATE TABLE match_insights (
    match_id INTEGER NOT NULL REFERENCES match_intelligence(id),
    fotmob_insight_key TEXT NOT NULL,   -- real localizedTextId, e.g. "insights_goals_team" - the real dedup key across re-syncs
    team_id INTEGER REFERENCES teams(id),
    player_id INTEGER REFERENCES players(id),
    priority INTEGER,
    text TEXT NOT NULL,                 -- FotMob's own real, ready-to-display sentence
    color TEXT,
    source TEXT NOT NULL DEFAULT 'fotmob',
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (match_id, fotmob_insight_key)
);

-- Real FotMob editorial article (content.postReview once a match has
-- finished, content.preReview before it - both real, published, with a
-- real headline/summary/image; filtered to the "en" language entry, never
-- LLM-authored here).
CREATE TABLE match_reviews (
    match_id INTEGER NOT NULL REFERENCES match_intelligence(id),
    kind TEXT NOT NULL CHECK (kind IN ('pre', 'post')),
    fotmob_review_id TEXT,
    title TEXT,
    description TEXT,
    image_url TEXT,
    content_url TEXT,
    published_at TEXT,
    source TEXT NOT NULL DEFAULT 'fotmob',
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (match_id, kind)
);
