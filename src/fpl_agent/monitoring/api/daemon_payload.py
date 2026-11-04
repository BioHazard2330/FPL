"""DAEMON - what the background system did and whether its state holds together: the last cycles from the run ledger and the
self-check, run fresh."""
import json


def build_daemon_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.self_check import run_checks
    from fpl_agent.scheduler.run_ledger import failing_steps

    conn = get_connection()
    try:
        runs = conn.execute("SELECT id, started_at, seconds, status, gated, errors, steps FROM pipeline_run ORDER BY id DESC LIMIT 24").fetchall()
        latest = dict(runs[0]) if runs else None
        if latest:
            latest["steps"] = sorted(json.loads(latest["steps"]), key=lambda s: -s["seconds"])[:14]
        return {
            "status": "ok", "checks": run_checks(conn), "failing": failing_steps(conn), "limit_seconds": 600,
            "runs": [{k: r[k] for k in ("id", "started_at", "seconds", "status", "errors")} for r in reversed(runs)], "latest": latest,
        }
    finally:
        conn.close()


build_daemon_payload.needs_context = False
