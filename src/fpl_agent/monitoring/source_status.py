import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceStatus:
    source_name: str
    last_success: str | None
    last_failure: str | None
    last_error: str | None
    latency_ms: int | None
    failure_count: int
    parser_version: str | None


def get_source_health(conn: sqlite3.Connection) -> list[SourceStatus]:
    rows = conn.execute(
        "SELECT source_name, last_success, last_failure, last_error, latency_ms, failure_count, parser_version "
        "FROM source_health ORDER BY source_name"
    ).fetchall()
    return [
        SourceStatus(
            source_name=r["source_name"],
            last_success=r["last_success"],
            last_failure=r["last_failure"],
            last_error=r["last_error"],
            latency_ms=r["latency_ms"],
            failure_count=r["failure_count"],
            parser_version=r["parser_version"],
        )
        for r in rows
    ]
