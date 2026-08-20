-- Real 2025-26 season scoring rules, needed for backtesting. The live `rules`
-- table is only ever populated for the CURRENT season by fpl_api_bootstrap sync
-- (FPL's API has no historical-rules endpoint) - so backtesting/harness.py's
-- season-scoped rule lookups silently defaulted every goals/assists rate to 0
-- for any historical season, on BOTH the predicted and actual sides identically,
-- reducing the "beats naive baseline" backtest result to an almost-meaningless
-- comparison of card-rate shrinkage alone (goals/assists cancelled out of the
-- comparison entirely). Confirmed live: a real 2025-26 match row (Gakpo, 90
-- minutes, 1 goal) reconstructed to 2.0 points instead of the real 7.0.
--
-- Source: verified against Fantasy Football Scout's official rules explainer
-- (fetched 2026-08-20) - these values match the position-differentiated goal
-- scoring introduced in the 2025-26 rule overhaul (the same season Defensive
-- Contribution was introduced) and are identical to this project's own
-- live-synced 2026-27 values, with no source found describing a change since.
-- Tier-2 sourced reconstruction (source='tier2_ffs_reconstructed'), explicitly
-- NOT Tier-1 official data - disclosed as such, never conflated with a real
-- fpl_api_bootstrap row.
INSERT INTO rules (rule_key, season, version, effective_date, source, value) VALUES
  ('scoring.goals_scored.GKP', '2025-26', 1, '2025-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '10'),
  ('scoring.goals_scored.DEF', '2025-26', 1, '2025-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '6'),
  ('scoring.goals_scored.MID', '2025-26', 1, '2025-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '5'),
  ('scoring.goals_scored.FWD', '2025-26', 1, '2025-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '4'),
  ('scoring.assists', '2025-26', 1, '2025-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '3'),
  ('scoring.yellow_cards', '2025-26', 1, '2025-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '-1');
