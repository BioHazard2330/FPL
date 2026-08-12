-- Decision journal (sections 71, 114). One row per major recommendation generated,
-- so a historical decision can be reconstructed from its stored evidence and model
-- version rather than relying on conversation memory.
CREATE TABLE decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail TEXT NOT NULL,
    model_version TEXT,
    confidence TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_decisions_created ON decisions(created_at);
