# Session 38 — 2026-09-02: Projection Engine Forensic Audit

Direct spec: determine whether the player xP model is systematically
under-projecting, audit first, fix only what's confirmed.

**Real event-conflation bug found + fixed (the headline finding)**:
`optimization/locked_squad.py::_xi_from_real_picks` called
`build_player_pool_for_ids` using the PICKS SNAPSHOT's own `event` field
instead of the real live/reference gameweek — for a squad synced mid-GW this
silently projected against the WRONG gameweek's fixtures. Confirmed live: the
dashboard was showing 40.6 projected points for a real path where the true
number (recomputed against the correct GW) was 46.1+. Fixed to use
`live_or_reference_event(conn)`.

**Real minutes-bucket zero-shrinkage bug found + fixed**:
`models/minutes_distribution.py::minutes_bucket_probabilities`'s empirical
branch used raw per-player frequency with no shrinkage toward a positional
prior — a thin real sample (a player with only 1-2 real matches) could swing
to an extreme P(60+)/P(0) with no real evidence backing it. Added
`_position_average_minutes_buckets` + `_position_avg_bucket_cache`, blended
via the project's own established `PRIOR_STRENGTH_MATCHES` empirical-Bayes
pattern.

**Real DefCon historical-data contamination bug found + fixed**:
`models/defensive_contribution.py`'s prior lookups included pre-2024/25
seasons, where DefCon wasn't tracked at all — those rows were fabricated
zeros, not real "no defensive contribution" observations, silently pulling
every prior toward zero. Added `_FIRST_TRACKED_DEFCON_SEASON = "2024/25"`,
filtered both `position_average_defcon_per90` and
`expected_defcon_actions_per90`'s prior lookup.

New/extended tests: `test_optimization_locked_squad.py` (event-conflation
regression), `test_minutes_distribution.py` (shrinkage + leakage), full suite
re-verified green against the DefCon fix.
