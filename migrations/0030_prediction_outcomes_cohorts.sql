-- migrations/0030_prediction_outcomes_cohorts.sql
-- Segmented accuracy measurement (2026-08-26, GW1-postmortem audit P0 item
-- 4). Two real, already-computed-at-prediction-time fields, captured so
-- future accuracy can be honestly segmented by cohort - position is
-- derivable from players.element_type at query time (no column needed);
-- nailed-vs-rotation is derivable from predicted_expected_minutes (already
-- a column). These two genuinely need to be captured AT prediction time,
-- since they reflect what the model believed THEN, not what's true now:
-- a cold-start basis or an availability read can both change week to week,
-- and segmenting by the CURRENT state of either would silently mix a
-- player's later, better-evidenced weeks into a cohort meant to measure
-- how the model does specifically when it was flying blind.
ALTER TABLE prediction_outcomes ADD COLUMN predicted_minutes_basis TEXT;
ALTER TABLE prediction_outcomes ADD COLUMN predicted_availability TEXT;
