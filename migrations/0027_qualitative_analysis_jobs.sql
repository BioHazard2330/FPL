-- migrations/0027_qualitative_analysis_jobs.sql
-- Zero-cost autonomous matchday queue (2026-08-22, matchday-autonomy pass).
-- Real architectural decision, made explicitly by the user rather than
-- assumed: no paid LLM API, no local-model substitute, standing free-
-- resources-only rule stays intact. Runtime data collection, match
-- finalization, and job creation are fully automatic (Python, no LLM);
-- only the actual qualitative reasoning step waits for the next real
-- Claude Code session to open and drain this queue. UNIQUE(match_id, phase)
-- is the idempotency key - re-detecting the same transition twice (e.g. the
-- fast live-match-poll daemon and the slower run-scheduled cycle both
-- observing the same FULL_TIME) must never create two jobs for the same
-- real event.
CREATE TABLE qualitative_analysis_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES match_intelligence(id),
    phase TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    evidence_summary TEXT,
    created_at TEXT NOT NULL,
    processed_at TEXT,
    error TEXT,
    UNIQUE(match_id, phase)
);
CREATE INDEX idx_qualitative_analysis_jobs_status ON qualitative_analysis_jobs(status);
