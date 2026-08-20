-- Real scoring rules for 2021-22 through 2024-25, needed to build ML-ensemble
-- training data (models/ml_ensemble.py) across multiple historical seasons -
-- same class of gap migration 0017 closed for 2025-26, extended backward.
--
-- Source/confidence: position-differentiated goal scoring (GKP/DEF/MID/FWD at
-- different point values) has been confirmed in place "since at least the
-- 2020-21 season" (multiple sources, fetched 2026-08-20). The official
-- premierleague.com "what's new for 2025/26" changelog lists Defensive
-- Contributions (new), bonus-point-system tweaks, and an assist-definition
-- simplification as that season's scoring changes - it does NOT list any
-- change to goals_scored point values, which is strong evidence they were
-- already at today's values before 2025-26. An explicitly 2024/25-dated
-- third-party scoring guide (footballfancast.com) independently states the
-- exact same values (GKP=10, DEF=6, MID=5) for that season. Tier-2 sourced
-- reconstruction (source='tier2_ffs_reconstructed', same label as 0017's),
-- not Tier-1 official data - disclosed as such. Confidence is good but not
-- certain for the earliest season here (2021-22) specifically, since no
-- source was found explicitly dated to that season - if ML training results
-- look implausible for that season in particular, re-verify it in isolation
-- before trusting it further.
INSERT INTO rules (rule_key, season, version, effective_date, source, value) VALUES
  ('scoring.goals_scored.GKP', '2021-22', 1, '2021-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '10'),
  ('scoring.goals_scored.DEF', '2021-22', 1, '2021-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '6'),
  ('scoring.goals_scored.MID', '2021-22', 1, '2021-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '5'),
  ('scoring.goals_scored.FWD', '2021-22', 1, '2021-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '4'),
  ('scoring.assists', '2021-22', 1, '2021-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '3'),
  ('scoring.yellow_cards', '2021-22', 1, '2021-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '-1'),

  ('scoring.goals_scored.GKP', '2022-23', 1, '2022-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '10'),
  ('scoring.goals_scored.DEF', '2022-23', 1, '2022-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '6'),
  ('scoring.goals_scored.MID', '2022-23', 1, '2022-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '5'),
  ('scoring.goals_scored.FWD', '2022-23', 1, '2022-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '4'),
  ('scoring.assists', '2022-23', 1, '2022-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '3'),
  ('scoring.yellow_cards', '2022-23', 1, '2022-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '-1'),

  ('scoring.goals_scored.GKP', '2023-24', 1, '2023-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '10'),
  ('scoring.goals_scored.DEF', '2023-24', 1, '2023-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '6'),
  ('scoring.goals_scored.MID', '2023-24', 1, '2023-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '5'),
  ('scoring.goals_scored.FWD', '2023-24', 1, '2023-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '4'),
  ('scoring.assists', '2023-24', 1, '2023-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '3'),
  ('scoring.yellow_cards', '2023-24', 1, '2023-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '-1'),

  ('scoring.goals_scored.GKP', '2024-25', 1, '2024-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '10'),
  ('scoring.goals_scored.DEF', '2024-25', 1, '2024-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '6'),
  ('scoring.goals_scored.MID', '2024-25', 1, '2024-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '5'),
  ('scoring.goals_scored.FWD', '2024-25', 1, '2024-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '4'),
  ('scoring.assists', '2024-25', 1, '2024-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '3'),
  ('scoring.yellow_cards', '2024-25', 1, '2024-08-01T00:00:00Z', 'tier2_ffs_reconstructed', '-1');
