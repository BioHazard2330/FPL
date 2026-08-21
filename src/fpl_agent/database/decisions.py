import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Decision:
    id: int
    decision_type: str
    summary: str
    detail: dict
    model_version: str | None
    confidence: str | None
    created_at: str


def log_decision(
    conn: sqlite3.Connection,
    decision_type: str,
    summary: str,
    detail: dict,
    model_version: str | None = None,
    confidence: str | None = None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO decisions (decision_type, summary, detail, model_version, confidence, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (decision_type, summary, json.dumps(detail), model_version, confidence, now),
    )
    conn.commit()
    return cur.lastrowid


def get_decision(conn: sqlite3.Connection, decision_id: int) -> Decision | None:
    row = conn.execute(
        "SELECT id, decision_type, summary, detail, model_version, confidence, created_at "
        "FROM decisions WHERE id=?",
        (decision_id,),
    ).fetchone()
    if row is None:
        return None
    return Decision(
        id=row["id"], decision_type=row["decision_type"], summary=row["summary"],
        detail=json.loads(row["detail"]), model_version=row["model_version"],
        confidence=row["confidence"], created_at=row["created_at"],
    )


def latest_decision_of_type(conn: sqlite3.Connection, decision_type: str) -> Decision | None:
    """Most recent already-logged decision of one type - a cheap read for a
    caller that wants the last real computed result (e.g. `fpl chips`'s
    wildcard/free-hit values) without re-running the expensive computation
    that produced it. See monitoring/dashboard.py's Chip Strategy panel
    (2026-08-21) for why this matters: wildcard_value/freehit_value each
    re-solve the full squad ILP, real minutes not milliseconds - baking that
    into every dashboard regen (itself already on a real per-cycle budget)
    would be the wrong tradeoff. Returns None if this type has never been
    logged - callers must treat that as "no value available yet," not zero."""
    row = conn.execute(
        "SELECT id, decision_type, summary, detail, model_version, confidence, created_at "
        "FROM decisions WHERE decision_type=? ORDER BY id DESC LIMIT 1",
        (decision_type,),
    ).fetchone()
    if row is None:
        return None
    return Decision(
        id=row["id"], decision_type=row["decision_type"], summary=row["summary"],
        detail=json.loads(row["detail"]), model_version=row["model_version"],
        confidence=row["confidence"], created_at=row["created_at"],
    )


def list_decisions(conn: sqlite3.Connection, limit: int = 20) -> list[Decision]:
    rows = conn.execute(
        "SELECT id, decision_type, summary, detail, model_version, confidence, created_at "
        "FROM decisions ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        Decision(
            id=r["id"], decision_type=r["decision_type"], summary=r["summary"],
            detail=json.loads(r["detail"]), model_version=r["model_version"],
            confidence=r["confidence"], created_at=r["created_at"],
        )
        for r in rows
    ]
