"""Who to cheer (`models/live_swing.py`): `/api/swing`, the gameweek in play, or `?event=N` to read a finished one back.
Held for 15 seconds, since FPL's live endpoint moves slowly against a page's polling."""
import threading
import time

_LOCK = threading.Lock()
_cache: dict[int | None, tuple[float, dict]] = {}
_TTL_SECONDS = 15.0


def _build(asked: int | None) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.ingestion.gw_stats import GwStatsFetchError, fetch_event_live
    from fpl_agent.ingestion.my_team import get_my_team_entry_id
    from fpl_agent.models import rank_engine as re
    from fpl_agent.models.effective_ownership import sample_season
    from fpl_agent.models.fixtures import live_or_reference_event
    from fpl_agent.models.live_bonus import compute_live_bonus
    from fpl_agent.models.live_forecast import fixture_states
    from fpl_agent.models.live_swing import swing

    conn = get_connection()
    try:
        event = asked if asked is not None else live_or_reference_event(conn)
        if event is None:
            return {"status": "not_live"}
        states = fixture_states(conn, event)
        if not any(s.status in ("live", "done") for s in states):
            return {"status": "not_live", "event": event}
        entry = get_my_team_entry_id(conn)
        picks = [{"player_id": r["player_id"], "multiplier": r["multiplier"], "is_vice": bool(r["is_vice_captain"]), "position": r["position"], "team_id": r["team_id"]} for r in conn.execute(
            "SELECT k.player_id, k.multiplier, k.is_vice_captain, et.singular_name_short AS position, p.team_id FROM my_team_picks k "
            "JOIN players p ON p.id = k.player_id JOIN element_types et ON et.id = p.element_type "
            "WHERE k.entry_id=? AND k.event=? ORDER BY k.squad_slot", (entry, event))] if entry is not None else []
        if not picks:
            return {"status": "no_picks", "event": event}
        field = re.build_field(conn, "top10k", for_event=event)
        if field is None:
            return {"status": "no_sample", "event": event}
        try:
            live = fetch_event_live(event)
        except GwStatsFetchError as exc:
            return {"status": "no_live_data", "event": event, "detail": str(exc)}
        stats = {el["id"]: el.get("stats") or {} for el in live.get("elements", [])}
        pending: dict[int, int] = {}
        for row in compute_live_bonus(conn, live):
            if not row.confirmed_bonus and row.provisional_bonus:
                pending[row.player_id] = pending.get(row.player_id, 0) + row.provisional_bonus
        own = {r["player_id"]: r["sum_multiplier"] / r["sample_size"] for r in conn.execute(
            "SELECT player_id, sum_multiplier, sample_size FROM player_sample_ownership_history WHERE event=? AND season=?", (event, sample_season(conn)))}
        eo, sample = (own, event) if own else (field.eo, field.sample_event)
        return {**swing(conn, event, picks, stats, eo, states, pending), "field": f"Top 10,000 managers, GW{sample} picks", "field_event": sample}
    finally:
        conn.close()


def build_swing_payload(ctx=None, params: dict | None = None) -> dict:
    raw = (params or {}).get("event")
    try:
        asked = int(raw) if raw is not None else None
    except ValueError:
        return {"status": "bad_request"}
    now = time.monotonic()
    with _LOCK:
        hit = _cache.get(asked)
        if hit and now - hit[0] < _TTL_SECONDS:
            return hit[1]
    payload = _build(asked)
    with _LOCK:
        _cache[asked] = (time.monotonic(), payload)
    return payload


build_swing_payload.needs_context = False
