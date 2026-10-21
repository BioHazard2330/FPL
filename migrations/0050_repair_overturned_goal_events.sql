-- FotMob reuses an event id when VAR overturns a goal: the same incident first
-- arrives as type "Goal", then as type "VAR" (decision "Goal ruled out"). The
-- sync's upsert updated the description but not the type, so seven overturned
-- goals stayed typed "Goal" and counted as goals in the match report, the live
-- charts and the match analyst. The upsert now updates the type; this repairs
-- the rows already stored. Their description is the only trace of the change.
UPDATE match_events SET event_type = 'VAR' WHERE event_type = 'Goal' AND description LIKE 'VAR%';
