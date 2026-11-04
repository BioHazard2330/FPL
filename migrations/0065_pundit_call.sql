-- The reasoned call Claude makes in a session from the week's dossier, scored each gameweek against the plan and the manager.
CREATE TABLE IF NOT EXISTS pundit_call (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event INTEGER NOT NULL,
    made_at TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pundit_call_event ON pundit_call(event);
