"""The Supercomputer (`models/supercomputer.py`): about twelve seconds to build, so one build per result and per day, kept in
memory and in `app_meta` so a restart does not pay for it again."""
import json
import threading
from datetime import datetime, timezone

_LOCK = threading.Lock()
_memory: tuple[str, dict] | None = None
_KEY = "supercomputer"


def build_supercomputer_payload(ctx=None, params: dict | None = None) -> dict:
    global _memory
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.supercomputer import run

    with _LOCK:
        conn = get_connection()
        try:
            scored = conn.execute("SELECT COUNT(*) AS n FROM fixtures WHERE team_h_score IS NOT NULL").fetchone()["n"]
            stamp = f"{scored}:{datetime.now(timezone.utc).date()}"
            if _memory is not None and _memory[0] == stamp:
                return _memory[1]
            row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (_KEY,)).fetchone()
            stored = json.loads(row["value"]) if row and row["value"] else None
            if stored and stored.get("stamp") == stamp:
                _memory = (stamp, stored["payload"])
                return stored["payload"]
            payload = run(conn)
            conn.execute(
                "INSERT INTO app_meta (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (_KEY, json.dumps({"stamp": stamp, "payload": payload}), datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            _memory = (stamp, payload)
            return payload
        finally:
            conn.close()


build_supercomputer_payload.needs_context = False
