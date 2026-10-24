"""THE LIVE ANALYST - the match as it stands, read the way a finished one is.

`/api/livestory?id=<match id>` runs the Match Analyst on a match in play: the
shots and goals so far, the result they deserve if the match were replayed,
minutes and chances in each game state to this minute, and substitutions
classified, including a starter taken off early called a probable injury at the
rate the stored stories give for that minute. Provisional by construction: the
story says so, and nothing in it is written to the database. Held for fifteen
seconds per match so many open tabs read one build."""
import threading
import time

_LOCK = threading.Lock()
_CACHE: dict[int, tuple[float, dict]] = {}
_TTL = 15.0


def build_live_story(ctx, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.match_analyst import analyse_live

    try:
        match_id = int((params or {}).get("id"))
    except (TypeError, ValueError):
        raise LookupError("'id' must be a real integer match id") from None
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(match_id)
        if hit and now - hit[0] < _TTL:
            return hit[1]
    conn = get_connection()
    try:
        story = analyse_live(conn, match_id)
    finally:
        conn.close()
    if story is None:
        raise LookupError(f"match {match_id} is not in play")
    payload = {"story": story, "minute": story["length"], "provisional": True}
    with _LOCK:
        _CACHE[match_id] = (now, payload)
    return payload


build_live_story.needs_context = False  # type: ignore[attr-defined]
