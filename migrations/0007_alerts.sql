-- Tracks alert delivery separately from action_required (which flags whether a
-- change needs user attention at all - alerted_at flags whether we've already
-- notified about it, so a re-run of the scheduler doesn't re-alert).
ALTER TABLE change_events ADD COLUMN alerted_at TEXT;
