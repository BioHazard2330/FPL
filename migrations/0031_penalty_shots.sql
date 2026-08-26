-- migrations/0031_penalty_shots.sql
-- Real, verified-live penalty-shot capture (2026-08-26, GW1-postmortem audit
-- P1 "penalty-duty extraction"). FotMob's real shotmap carries a genuine
-- `situation` field per shot - confirmed live before building this (2 real
-- penalty shots found across GW1's 10 real matches, `situation == 'Penalty'`).
-- Deliberately NOT yet fed into any xP adjustment - see
-- models/penalty_duty.py's own module docstring for the real reason
-- (data volume, not code, is the current constraint: 2 real observations
-- league-wide is nowhere near enough to fit a real, defensible per-90 rate).
ALTER TABLE player_match_state ADD COLUMN penalty_shots INTEGER;
ALTER TABLE player_match_state ADD COLUMN penalty_goals INTEGER;
