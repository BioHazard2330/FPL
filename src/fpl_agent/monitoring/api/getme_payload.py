"""GET ME X - the cheapest route to a player this gameweek (`optimization/week_plan.route_to`), cached per player and
plan build so the same question is not solved twice."""
_CACHE: dict[tuple, dict] = {}


def build_getme_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.optimization.week_plan import latest_week_plan, route_to

    try:
        target = int((params or {}).get("player", [""])[0] if isinstance((params or {}).get("player"), list) else (params or {}).get("player"))
    except (TypeError, ValueError):
        return {"status": "bad_request"}
    conn = get_connection()
    try:
        stored = latest_week_plan(conn)
        key = (target, stored[1] if stored else None)
        if key not in _CACHE:
            _CACHE.clear() if len(_CACHE) > 64 else None
            _CACHE[key] = route_to(conn, target) or {"status": "no_squad"}
        return _CACHE[key]
    finally:
        conn.close()
