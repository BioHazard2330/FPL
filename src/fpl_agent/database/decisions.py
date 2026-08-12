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
