-- Each frozen prediction's parts (appearance, goals, assists, bonus, clean sheet, conceded, cards, defensive
-- contribution, saves) and minutes buckets as JSON, so a finished gameweek can be laid against FPL's own per-part
-- points without rebuilding the projection.
ALTER TABLE prediction_outcomes ADD COLUMN predicted_components TEXT;
