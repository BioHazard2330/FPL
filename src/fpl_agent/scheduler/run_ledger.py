"""THE RUN LEDGER - what each `run-scheduled` cycle actually did.

The cycle is a long chain of steps, each "not fatal": a failure is logged and the cycle carries on. That is right for the
cycle and wrong for the manager, because a step can then fail for days with nothing on any screen (Understat's xG backfill,
the strategic-plan trigger). The ledger listens to the scheduler's own log lines, so no step has to change: each line is a
step, its time the gap to the next. Errors from any `fpl_agent` logger count against the cycle.

Lines go to a journal file as they happen, never to the database: the cycle may hold a write transaction, and a killed
process must leave a trace. A journal found at the start of a cycle belongs to a cycle that never finished (the task
scheduler's 10-minute limit, a shutdown) and is recorded as `killed`. A cycle that only decided not to run records nothing.

A step that failed in `FAILING_RUNS` cycles in a row, or a killed cycle, becomes a `daemon_failing` change event, so it
reaches the manager as an alert once a day."""
import contextlib
import json
import logging
import re
import sqlite3
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

_logger = logging.getLogger("fpl_agent.run_ledger")
JOURNAL = "run_ledger.jsonl"
KEEP_RUNS = 300
FAILING_RUNS = 3
_NOT_A_RUN = ("skipped:", "exiting cleanly", "deferred:")


def _clean(message: str) -> str:
    return message.splitlines()[0].removeprefix("run-scheduled ").removeprefix("run-scheduled: ")[:200] if message else ""


class _Listener(logging.Handler):
    def __init__(self, path: Path) -> None:
        super().__init__(logging.INFO)
        self.rows: list[dict] = []
        self.path = path

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.ERROR and record.name != "fpl_agent.scheduler":
            return
        row = {"t": record.created, "level": record.levelname, "text": _clean(record.getMessage())}
        self.rows.append(row)
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except OSError:
            pass


def steps_from(rows: list[dict], end: float) -> list[dict]:
    out = []
    for i, r in enumerate(rows):
        after = rows[i + 1]["t"] if i + 1 < len(rows) else end
        out.append({"text": r["text"], "level": r["level"], "seconds": round(max(after - r["t"], 0.0), 1)})
    return out


def is_a_run(rows: list[dict]) -> bool:
    return bool(rows) and not (len(rows) <= 2 and any(m in r["text"] for r in rows for m in _NOT_A_RUN))


def _write(conn: sqlite3.Connection, started: float, ended: float | None, status: str, gated: bool, rows: list[dict]) -> None:
    last = rows[-1]["t"] if rows else started
    end = ended if ended is not None else last
    conn.execute(
        "INSERT INTO pipeline_run (started_at, finished_at, seconds, status, gated, errors, steps) VALUES (?,?,?,?,?,?,?)",
        (datetime.fromtimestamp(started, timezone.utc).isoformat(), datetime.fromtimestamp(end, timezone.utc).isoformat() if ended else None,
         round(end - started, 1), status, int(gated), sum(1 for r in rows if r["level"] in ("ERROR", "CRITICAL")),
         json.dumps(steps_from(rows, end))),
    )
    conn.execute("DELETE FROM pipeline_run WHERE id NOT IN (SELECT id FROM pipeline_run ORDER BY id DESC LIMIT ?)", (KEEP_RUNS,))
    conn.commit()


def _salvage(path: Path, conn_factory: Callable[[], sqlite3.Connection]) -> None:
    """A journal left behind is a cycle that died."""
    if not path.exists():
        return
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        rows = []
    if is_a_run(rows):
        conn = conn_factory()
        try:
            _write(conn, rows[0]["t"], None, "killed", False, rows)
            alert_failures(conn)
        finally:
            conn.close()
    path.unlink(missing_ok=True)


def _norm(text: str) -> str:
    return re.sub(r"\d+", "#", text)[:90]


def failing_steps(conn: sqlite3.Connection, runs: int = FAILING_RUNS) -> list[str]:
    """Error lines present in each of the last `runs` cycles that ran."""
    rows = conn.execute("SELECT steps FROM pipeline_run ORDER BY id DESC LIMIT ?", (runs,)).fetchall()
    if len(rows) < runs:
        return []
    sets = [{_norm(s["text"]) for s in json.loads(r["steps"]) if s["level"] in ("ERROR", "CRITICAL")} for r in rows]
    return sorted(set.intersection(*sets))


def alert_failures(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """A `daemon_failing` event for each repeatedly failing step and a killed last cycle, at most one a day for each."""
    from fpl_agent.ingestion.change_detection import record_event

    now = now or datetime.now(timezone.utc)
    last = conn.execute("SELECT status, started_at, seconds FROM pipeline_run ORDER BY id DESC LIMIT 1").fetchone()
    problems = list(failing_steps(conn))
    if last is not None and last["status"] == "killed":
        problems.append(f"a cycle was cut off after {last['seconds']:.0f}s")
    since = (now - timedelta(days=1)).isoformat()
    fired = 0
    for p in problems:
        if conn.execute("SELECT 1 FROM change_events WHERE event_type = 'daemon_failing' AND old_value = ? AND detected_at > ?", (p, since)).fetchone():
            continue
        record_event(conn, "daemon_failing", "system", 0, p, "failing", now.isoformat(), "run_ledger", "OBSERVED", "HIGH", fpl_impact=p)
        fired += 1
    if fired:
        conn.commit()
    return fired


@contextlib.contextmanager
def record_run(gated: bool, data_dir: Path, conn_factory: Callable[[], sqlite3.Connection]) -> Iterator[_Listener]:
    path = data_dir / JOURNAL
    try:
        _salvage(path, conn_factory)
    except Exception:
        _logger.exception("run ledger: could not read an earlier journal")
        path.unlink(missing_ok=True)
    listener = _Listener(path)
    root = logging.getLogger("fpl_agent")
    root.addHandler(listener)
    started = time.time()
    failed = False
    try:
        yield listener
    except BaseException:
        failed = True
        raise
    finally:
        root.removeHandler(listener)
        try:
            if is_a_run(listener.rows):
                conn = conn_factory()
                try:
                    errors = any(r["level"] in ("ERROR", "CRITICAL") for r in listener.rows)
                    _write(conn, started, time.time(), "failed" if failed else "errors" if errors else "ok", gated, listener.rows)
                    alert_failures(conn)
                finally:
                    conn.close()
            path.unlink(missing_ok=True)
        except Exception:
            _logger.exception("run ledger: could not record this cycle")
