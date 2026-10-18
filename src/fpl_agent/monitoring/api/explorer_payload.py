"""THE EXPLORER: every player worth looking at, in one table the reader can sort
and filter, with the model's numbers beside the season line.

One row per player with minutes this season or at least 0.5% ownership. The
columns that decide a transfer sit together: price, ownership, expected points
for the next gameweek and the next five, expected points per million, form,
minutes played as a share of the minutes available, goal involvement per 90, how
many points the chances say he is running above or below (the luck audit's z),
availability and the next three fixtures with their difficulty. Nothing is
combined into a score: the table sorts on the figures as they are and says what
each one is.

Numerical assumptions: expected points are the model's own (`expected_points_
window`, one and five gameweeks, the second with its per-extra-fixture rotation
damping); minutes share is minutes over 90 times the gameweeks played by the
club's league; luck is `luck_audit.season_luck`, over the whole season, and is
absent below 90 minutes. The payload is rebuilt at most every ten minutes and
held in memory: a cold build projects about 450 players twice, which is why it
runs in the server's background refresh and not on the request."""
import threading
import time
from datetime import datetime, timezone

from fpl_agent.models.projection_memo import projection_memo
from fpl_agent.monitoring.api.fixture_context import fixture_context_by_team_code
from fpl_agent.monitoring.api.photos import attach_photo_codes
from fpl_agent.monitoring.dashboard.context import DashboardContext

_LOCK = threading.Lock()
_cached: dict | None = None
_cached_at = 0.0
_TTL_SECONDS = 600.0
_MIN_OWNED = 0.5
WINDOW_GW = 5


def _rows(conn) -> list:
    return conn.execute(
        "SELECT p.id AS player_id, p.web_name, p.first_name, p.second_name, p.status, p.news, p.team_id, "
        "       t.short_name AS team_short, t.code AS team_code, et.singular_name_short AS position, "
        "       s.now_cost, s.form, s.points_per_game, s.total_points, s.minutes, s.starts, s.goals_scored, s.assists, "
        "       s.expected_goals, s.expected_assists, s.bonus, s.chance_of_playing_next_round AS chance, "
        "       (SELECT selected_by_percent FROM player_ownership_history WHERE player_id = p.id AND valid_until IS NULL) AS owned "
        "FROM players p JOIN teams t ON t.id = p.team_id JOIN element_types et ON et.id = p.element_type "
        "LEFT JOIN player_stats_snapshot s ON s.id = (SELECT MAX(id) FROM player_stats_snapshot WHERE player_id = p.id) "
        "WHERE p.removed = 0"
    ).fetchall()


def _build() -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.expected_points import expected_points_window
    from fpl_agent.models.fixtures import _reference_event
    from fpl_agent.models.luck_audit import season_luck
    from fpl_agent.optimization.week_plan import light_squad_state

    conn = get_connection()
    memo = projection_memo(conn)
    memo.__enter__()
    try:
        event = _reference_event(conn)
        state = light_squad_state(conn)
        mine = set(state["squad_ids"]) if state else set()
        played = conn.execute(
            "SELECT COUNT(DISTINCT event) AS n FROM player_gw_stats"
        ).fetchone()["n"] or 1
        luck = {r["player_id"]: r for r in season_luck(conn) if r["minutes"] >= 90}
        rows = [r for r in _rows(conn) if (r["minutes"] or 0) > 0 or (r["owned"] or 0) >= _MIN_OWNED]
        fixtures = fixture_context_by_team_code(conn, {r["team_id"] for r in rows}, n_gw=3)
        out = []
        for r in rows:
            try:
                one = expected_points_window(conn, r["player_id"], 1, from_event=event)
                five = expected_points_window(conn, r["player_id"], WINDOW_GW, from_event=event)
            except Exception:
                continue
            price = r["now_cost"] / 10 if r["now_cost"] is not None else None
            minutes = r["minutes"] or 0
            lk = luck.get(r["player_id"])
            out.append({
                "player_id": r["player_id"], "name": r["web_name"],
                "full_name": " ".join(x for x in (r["first_name"], r["second_name"]) if x) or r["web_name"],
                "team_id": r["team_id"], "team_short": r["team_short"], "team_code": r["team_code"],
                "position": r["position"], "mine": r["player_id"] in mine,
                "price": price, "owned": r["owned"],
                "xp_next": round(one.total_median, 2), "xp_five": round(five.total_median, 2),
                "xp_per_m": round(five.total_median / price, 2) if price else None,
                "form": float(r["form"]) if r["form"] is not None else None,
                "ppg": float(r["points_per_game"]) if r["points_per_game"] is not None else None,
                "points": r["total_points"], "minutes": minutes,
                "minutes_share": round(min(minutes / (90 * played), 1.0), 2),
                "g_a_90": round((r["goals_scored"] + r["assists"]) / minutes * 90, 2) if minutes >= 180 and r["goals_scored"] is not None else None,
                "xgi_90": round(((r["expected_goals"] or 0) + (r["expected_assists"] or 0)) / minutes * 90, 2) if minutes >= 180 else None,
                "luck": lk["luck"] if lk else None, "luck_z": lk["z"] if lk else None,
                "deserved_ppg": round(lk["deserved"] / lk["gws"], 2) if lk and lk["gws"] else None,
                "actual_ppg": round(lk["actual"] / lk["gws"], 2) if lk and lk["gws"] else None,
                "status": r["status"], "chance": r["chance"], "news": r["news"] or None,
                "fixtures": [
                    {"opponent": f["opponent_short"], "home": f["is_home"], "difficulty": f["difficulty"]}
                    for f in fixtures.get(str(r["team_code"]), [])[:3]
                ],
            })
        out.sort(key=lambda p: -p["xp_five"])
        payload = {"event": event, "generated_at": datetime.now(timezone.utc).isoformat(), "window": WINDOW_GW, "players": out}
        return attach_photo_codes(conn, payload)
    finally:
        memo.__exit__(None, None, None)
        conn.close()


def build_explorer_payload(ctx: DashboardContext) -> dict:
    global _cached, _cached_at
    now = time.monotonic()
    with _LOCK:
        if _cached is not None and now - _cached_at < _TTL_SECONDS:
            return _cached
    payload = _build()
    with _LOCK:
        _cached, _cached_at = payload, time.monotonic()
    return payload


build_explorer_payload.needs_context = False


def run_explorer_refresh_loop(stop_event: threading.Event, interval: float = 540.0, should_run=None) -> None:
    global _cached, _cached_at
    while not stop_event.is_set():
        if stop_event.wait(interval):
            break
        if should_run is not None and not should_run():
            continue
        try:
            payload = _build()
            with _LOCK:
                _cached, _cached_at = payload, time.monotonic()
        except Exception:
            import logging
            logging.getLogger("fpl_agent.dashboard").exception("background explorer refresh failed - keeping the previous result")
