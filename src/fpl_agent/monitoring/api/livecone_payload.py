"""WHERE THIS GAMEWEEK ENDS: the live forecast payload.

Needs the gameweek's picks (published after the deadline), FPL's live points,
and the effective-ownership sample for the field. Outside a gameweek in progress
it says so and returns nothing to draw; it never forecasts off a stale state.
Held in memory for 25 seconds, since the live endpoint it reads moves slowly
relative to a page refresh. See `models/live_forecast.py` for the method."""
import threading
import time
from datetime import datetime, timezone

from fpl_agent.monitoring.api.photos import attach_photo_codes
from fpl_agent.monitoring.dashboard.context import DashboardContext

_LOCK = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}
_TTL_SECONDS = 25.0


def _build(kind: str) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.ingestion.gw_stats import GwStatsFetchError, fetch_event_live
    from fpl_agent.ingestion.my_team import get_my_team_entry_id
    from fpl_agent.models import rank_engine as re
    from fpl_agent.models.fixtures import live_or_reference_event
    from fpl_agent.models.live_forecast import fixture_states, forecast_event, forecast_scorecard, log_forecast

    conn = get_connection()
    try:
        event = live_or_reference_event(conn)
        if event is None:
            return {"status": "not_live"}
        states = fixture_states(conn, event)
        if not any(s.status in ("live", "done") for s in states):
            return {"status": "not_live", "event": event, "detail": "no match of this gameweek has kicked off"}
        entry = get_my_team_entry_id(conn)
        if all(s.status == "done" for s in states):
            settled = {"status": "settled", "event": event, "detail": "every match of this gameweek has finished"}
            final = conn.execute(
                "SELECT points FROM my_team_gw_summary WHERE entry_id=? AND event=?", (entry, event),
            ).fetchone() if entry is not None else None
            if final is not None and final["points"] is not None:
                settled["scorecard"] = forecast_scorecard(conn, event, float(final["points"]))
            return settled
        picks = [
            (r["player_id"], r["multiplier"]) for r in conn.execute(
                "SELECT player_id, multiplier FROM my_team_picks WHERE entry_id=? AND event=?", (entry, event),
            )
        ] if entry is not None else []
        if not picks:
            return {"status": "no_picks", "event": event, "detail": "your picks for this gameweek have not synced yet"}
        field_model = re.build_field(conn, kind)
        if field_model is None:
            return {"status": "no_sample", "event": event, "detail": "no effective-ownership sample has been collected"}
        try:
            payload = fetch_event_live(event)
        except GwStatsFetchError as exc:
            return {"status": "no_live_data", "event": event, "detail": str(exc)}
        stats = {el["id"]: el.get("stats") or {} for el in payload.get("elements", [])}
        live_points = {pid: s.get("total_points", 0) for pid, s in stats.items()}
        live_minutes = {pid: s.get("minutes", 0) for pid, s in stats.items()}
        f = forecast_event(conn, event, picks, live_points, live_minutes, field_model, re.population_sd(conn))
        try:
            log_forecast(conn, event, f)
        except Exception:
            pass
        names = {
            r["id"]: {"name": r["web_name"], "team_short": r["short_name"], "team_code": r["code"], "position": r["position"]}
            for r in conn.execute(
                "SELECT p.id, p.web_name, t.short_name, t.code, et.singular_name_short AS position "
                "FROM players p JOIN teams t ON t.id = p.team_id JOIN element_types et ON et.id = p.element_type"
            )
        }
        result = {
            "status": "ok", "event": event, "generated_at": datetime.now(timezone.utc).isoformat(),
            "field": {"kind": field_model.kind, "label": field_model.label},
            "now": round(f.now_points, 1), "forecast": {"mean": round(f.mean, 1), "p10": round(f.p10, 1), "p50": round(f.p50, 1), "p90": round(f.p90, 1)},
            "field_now": round(f.field_now, 1), "field_forecast": round(f.field_mean, 1), "edge": f.edge,
            "fixtures_left": f.fixtures_left, "fixtures_live": f.fixtures_live,
            "players": [{**p, **names.get(p["player_id"], {})} for p in f.players],
            "axis": {"min": -re.HIST_RANGE, "max": re.HIST_RANGE, "bins": re.HIST_BINS},
        }
        return attach_photo_codes(conn, result)
    finally:
        conn.close()


def build_livecone_payload(ctx: DashboardContext, params: dict | None = None) -> dict:
    kind = (params or {}).get("kind", "population")
    if kind not in ("population", "top10k"):
        raise LookupError("kind must be population or top10k")
    now = time.monotonic()
    with _LOCK:
        hit = _cache.get(kind)
        if hit and now - hit[0] < _TTL_SECONDS:
            return hit[1]
    payload = _build(kind)
    with _LOCK:
        _cache[kind] = (time.monotonic(), payload)
    return payload


build_livecone_payload.needs_context = False
