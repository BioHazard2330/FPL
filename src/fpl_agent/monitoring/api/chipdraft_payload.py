"""CHIP DRAFTS - a wildcard or free hit squad for a chosen gameweek (`optimization/chip_draft.chip_draft`, cached per chip,
week and plan build) and the stored wildcard ladder."""
_CACHE: dict[tuple, dict] = {}


def _one(params: dict | None, key: str):
    v = (params or {}).get(key)
    return v[0] if isinstance(v, list) else v


def build_chipdraft_payload(ctx=None, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.projection_memo import projection_memo
    from fpl_agent.optimization.chip_draft import ladder_events, stored_ladder
    from fpl_agent.optimization.week_plan import latest_week_plan

    conn = get_connection()
    try:
        chip, event = _one(params, "chip"), _one(params, "event")
        if not chip:
            return {"status": "ok", "ladder": stored_ladder(conn),
                    "events": {c: ladder_events(conn, c) for c in ("wildcard", "freehit")}}
        try:
            event = int(event)
        except (TypeError, ValueError):
            return {"status": "bad_request"}
        if event not in ladder_events(conn, chip):
            return {"status": "not_in_hand", "chip": chip, "event": event}
        stored = latest_week_plan(conn)
        key = (chip, event, stored[1] if stored else None)
        if key not in _CACHE:
            from fpl_agent.optimization.chip_draft import chip_draft

            if len(_CACHE) > 24:
                _CACHE.clear()
            with projection_memo(conn):
                _CACHE[key] = chip_draft(conn, chip, event) or {"status": "no_squad"}
        return _CACHE[key]
    finally:
        conn.close()
