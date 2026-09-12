-- migrations/0043_match_intelligence_lineup_type.sql
-- Real FotMob `content.lineup.lineupType` field ("predicted" for a
-- third-party pre-match guess, "standard" for the real lineup that was
-- actually used) - `player_match_state` gets populated from either kind,
-- and nothing previously recorded which one a given match's rows are, so
-- lineup_state.py could not tell a "predicted" lineup from a genuinely
-- confirmed one and reported both as CONFIRMED_STARTING/CONFIRMED_BENCHED.

ALTER TABLE match_intelligence ADD COLUMN lineup_type TEXT;
