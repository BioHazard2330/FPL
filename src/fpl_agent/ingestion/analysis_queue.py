"""Zero-cost qualitative-analysis job queue (2026-08-22, matchday-autonomy
pass). Real, explicit user decision behind this module's existence: no paid
LLM API call, no local-model substitute - the standing free-resources-only
rule stays intact. Everything up to "ready for analysis" (evidence sync,
FULL_TIME/HALFTIME detection, this queue row) is fully automatic Python,
same trust boundary this project draws everywhere else (Python never
fabricates football judgement). Only the actual qualitative reasoning step
waits for a real Claude Code session to open and drain this queue - see
`.claude/hooks/queue_check.py`, which surfaces pending jobs automatically at
session start so a human never has to remember to check.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class AnalysisJob:
    id: int
    match_id: int
    fotmob_match_id: str
    phase: str
    status: str
    evidence_summary: str | None
    created_at: str
    home_name: str
    away_name: str
    kickoff_utc: str | None


def enqueue_analysis_job(
    conn: sqlite3.Connection, match_id: int, phase: str, evidence_summary: str | None = None,
) -> bool:
    """Idempotent per (match_id, phase) - the real reason this project's
    two independent detectors (the fast live-match-poll daemon and the
    slower run-scheduled cycle) can both call this for the same real
    transition without ever creating two jobs for one event. A pending or
    already-processing job is left untouched; a done job is never reset
    (a real analysis already exists for it); a failed job is reset to
    pending so the next queue drain retries it automatically. Returns True
    only when this call actually created or reset a job."""
    existing = conn.execute(
        "SELECT id, status FROM qualitative_analysis_jobs WHERE match_id=? AND phase=?",
        (match_id, phase),
    ).fetchone()
    now = datetime.now(timezone.utc).isoformat()
    if existing is None:
        conn.execute(
            "INSERT INTO qualitative_analysis_jobs (match_id, phase, status, evidence_summary, created_at) "
            "VALUES (?,?,'pending',?,?)",
            (match_id, phase, evidence_summary, now),
        )
        conn.commit()
        return True
    if existing["status"] == "failed":
        conn.execute(
            "UPDATE qualitative_analysis_jobs SET status='pending', evidence_summary=?, error=NULL, "
            "processed_at=NULL WHERE id=?",
            (evidence_summary, existing["id"]),
        )
        conn.commit()
        return True
    return False


def list_pending_jobs(conn: sqlite3.Connection) -> list[AnalysisJob]:
    rows = conn.execute(
        "SELECT j.id, j.match_id, j.phase, j.status, j.evidence_summary, j.created_at, "
        "mi.fotmob_match_id, mi.kickoff_utc, ht.name AS home_name, at.name AS away_name "
        "FROM qualitative_analysis_jobs j "
        "JOIN match_intelligence mi ON mi.id = j.match_id "
        "JOIN teams ht ON ht.id = mi.home_team_id JOIN teams at ON at.id = mi.away_team_id "
        "WHERE j.status IN ('pending','processing') "
        "ORDER BY j.created_at"
    ).fetchall()
    return [
        AnalysisJob(
            id=r["id"], match_id=r["match_id"], fotmob_match_id=r["fotmob_match_id"], phase=r["phase"],
            status=r["status"], evidence_summary=r["evidence_summary"], created_at=r["created_at"],
            home_name=r["home_name"], away_name=r["away_name"], kickoff_utc=r["kickoff_utc"],
        )
        for r in rows
    ]


def mark_job_status(conn: sqlite3.Connection, job_id: int, status: str, error: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE qualitative_analysis_jobs SET status=?, error=?, processed_at=? WHERE id=?",
        (status, error, now, job_id),
    )
    conn.commit()


def supersede_stale_halftime_jobs(conn: sqlite3.Connection) -> int:
    """Real gap found 2026-08-26: a pending HALFTIME job for a match that has
    since reached FULL_TIME (the common case once a session opens hours or
    days after the actual match, e.g. this project's own GW1 backlog) has no
    remaining value - the FULL_TIME analysis supersedes it entirely, and
    spending real reasoning effort producing a "how it looked at halftime"
    writeup for a match that finished days ago is exactly the wasted-noise
    class of work section S/analysis-queue's own idempotency design is meant
    to prevent. Marks such jobs 'skipped' (not 'done' - no analysis was
    actually written, this must stay distinguishable from real completed
    work) rather than silently deleting them, so the real automatic-detection
    event that created them stays auditable. Returns the number superseded."""
    rows = conn.execute(
        "SELECT j.id FROM qualitative_analysis_jobs j JOIN match_intelligence mi ON mi.id = j.match_id "
        "WHERE j.phase='HALFTIME' AND j.status IN ('pending','processing') AND mi.status='FULL_TIME'"
    ).fetchall()
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        conn.execute(
            "UPDATE qualitative_analysis_jobs SET status='skipped', "
            "error='superseded by FULL_TIME analysis', processed_at=? WHERE id=?",
            (now, r["id"]),
        )
    if rows:
        conn.commit()
    return len(rows)


def mark_job_done_for_match_phase(conn: sqlite3.Connection, match_id: int, phase: str) -> None:
    """Called by `fpl match-analyze` right after a successful apply_match_
    analysis - closes the loop without match-analyze needing to know job
    ids. A genuine no-op (0 rows affected) when no job row exists for this
    (match, phase) - e.g. an analysis run by hand before this queue existed
    for the match, or before the automatic detector ever saw it."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE qualitative_analysis_jobs SET status='done', error=NULL, processed_at=? "
        "WHERE match_id=? AND phase=?",
        (now, match_id, phase),
    )
    conn.commit()
