"""`/api/council`: every source's vote on this gameweek's moves and armband (`models/council.py`), cached 60 seconds."""
import threading
import time

_CACHE: dict[str, tuple[float, dict]] = {}
_LOCK = threading.Lock()
TTL = 60.0


def build_council_payload(ctx=None, params: dict | None = None) -> dict:
    with _LOCK:
        hit = _CACHE.get("council")
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.council import council

    conn = get_connection()
    try:
        out = council(conn)
    finally:
        conn.close()
    with _LOCK:
        _CACHE["council"] = (time.time(), out)
    return out


build_council_payload.needs_context = False
