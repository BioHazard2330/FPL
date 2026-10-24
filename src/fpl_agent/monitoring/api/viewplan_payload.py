"""MY VIEW - the plan under a manager's own opinion of the players.

`/api/viewplan?scales=12:0.75,411:1.1` re-runs the planner's move selection with
each named player's projection multiplied by his scale in every gameweek. The
answer is the moves, their gains and the difference from the stored plan, so a
manager who thinks a player is drifting can see exactly what that belief costs or
changes. A scale is an opinion, not data: the evidence on whether recent form
carries is on the player's form line, and the planner itself is untouched.

A build takes 10-40 seconds, so answers are held for ten minutes per (scales,
stored plan) and one build runs at a time."""
import threading
import time

_LOCK = threading.Lock()
_CACHE: dict = {}
_TTL = 600.0
_MAX_PLAYERS = 12


def parse_scales(raw: str | None) -> dict[int, float]:
    out: dict[int, float] = {}
    for part in (raw or "").split(","):
        if not part.strip():
            continue
        pid, _, val = part.partition(":")
        try:
            p, v = int(pid), float(val)
        except ValueError:
            raise LookupError(f"bad scale {part!r}: expected player_id:factor") from None
        if not 0.0 <= v <= 3.0:
            raise LookupError(f"scale for {p} must be between 0 and 3")
        out[p] = v
    if len(out) > _MAX_PLAYERS:
        raise LookupError(f"at most {_MAX_PLAYERS} players")
    return out


def build_view_plan(ctx, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.optimization.week_plan import latest_week_plan, plan_with_view

    scales = parse_scales((params or {}).get("scales"))
    conn = get_connection()
    try:
        stored = latest_week_plan(conn)
        base_moves = [(m["out"]["player_id"], m["into"]["player_id"]) for m in stored[0].get("moves", [])] if stored else []
        key = (tuple(sorted(scales.items())), stored[2] if stored else None)
        with _LOCK:
            hit = _CACHE.get("entry")
            if hit and hit["key"] == key and time.time() - hit["at"] < _TTL:
                result = hit["result"]
            else:
                result = plan_with_view(conn, scales)
                _CACHE["entry"] = {"key": key, "at": time.time(), "result": result}
        if result is None:
            raise LookupError("no synced squad to plan for")
        mine = [(m["out"]["player_id"], m["into"]["player_id"]) for m in result["moves"]]
        return {**result, "same_as_stored": sorted(mine) == sorted(base_moves), "stored_moves": base_moves}
    finally:
        conn.close()


build_view_plan.needs_context = False  # type: ignore[attr-defined]
