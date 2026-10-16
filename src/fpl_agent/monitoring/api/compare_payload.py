"""COMPARE - two players, side by side, on the numbers that decide a transfer.

`/api/players` is the searchable index (every non-removed player with the few
fields a picker needs). `/api/compare?a=<id>&b=<id>` reads one player's season
line from the stored snapshot, projects him with the same model every other
screen uses (next gameweek and the next five), and lays the two out as rows. A
row carries both values and which side the arithmetic favours; nothing here
issues a verdict the model has not already made. The gap that matters is shown
beside the model's own measured error so a one-point difference is not read as
a decision.

Reads stored rows plus two projections per player (about 0.3s); no dashboard
context."""
import sqlite3

from fpl_agent.monitoring.api.fixture_context import fixture_context_by_team_code
from fpl_agent.monitoring.api.photos import attach_photo_codes
from fpl_agent.monitoring.dashboard.context import DashboardContext

_WINDOW_GW = 5


def build_players_index(ctx: DashboardContext) -> dict:
    from fpl_agent.database.connection import get_connection

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT p.id AS player_id, p.web_name, p.first_name, p.second_name, p.status, t.short_name AS team_short, "
            "       t.code AS team_code, et.singular_name_short AS position, s.now_cost, "
            "       (SELECT selected_by_percent FROM player_ownership_history WHERE player_id = p.id AND valid_until IS NULL) AS owned "
            "FROM players p JOIN teams t ON t.id = p.team_id JOIN element_types et ON et.id = p.element_type "
            "LEFT JOIN player_stats_snapshot s ON s.id = (SELECT MAX(id) FROM player_stats_snapshot WHERE player_id = p.id) "
            "WHERE p.removed = 0 ORDER BY owned DESC NULLS LAST, p.web_name"
        ).fetchall()
        players = [
            {
                "player_id": r["player_id"], "name": r["web_name"],
                "full_name": " ".join(x for x in (r["first_name"], r["second_name"]) if x),
                "team_short": r["team_short"], "team_code": r["team_code"], "position": r["position"],
                "price": r["now_cost"] / 10 if r["now_cost"] is not None else None, "owned": r["owned"], "status": r["status"],
            }
            for r in rows
        ]
        return attach_photo_codes(conn, {"players": players})
    finally:
        conn.close()


build_players_index.needs_context = False


def _next_event(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT MIN(event) AS e FROM fixtures WHERE finished=0 AND event IS NOT NULL").fetchone()
    return row["e"] if row else None


def _player(conn: sqlite3.Connection, player_id: int, event: int | None, mine: set[int]) -> dict:
    from fpl_agent.models.expected_points import expected_points, expected_points_window
    from fpl_agent.optimization.week_plan import _price_trends, _set_piece_duties, _solio_next, _start_percents

    p = conn.execute(
        "SELECT p.id, p.web_name, p.first_name, p.second_name, p.status, p.news, p.team_id, t.name AS team_name, "
        "       t.short_name AS team_short, t.code AS team_code, et.singular_name_short AS position, "
        "       s.now_cost, s.total_points, s.form, s.points_per_game, s.minutes, s.starts, s.goals_scored, s.assists, "
        "       s.expected_goals, s.expected_assists, s.bonus, s.clean_sheets, s.defensive_contribution, "
        "       s.chance_of_playing_next_round AS chance, "
        "       (SELECT selected_by_percent FROM player_ownership_history WHERE player_id = p.id AND valid_until IS NULL) AS owned "
        "FROM players p JOIN teams t ON t.id = p.team_id JOIN element_types et ON et.id = p.element_type "
        "LEFT JOIN player_stats_snapshot s ON s.id = (SELECT MAX(id) FROM player_stats_snapshot WHERE player_id = p.id) "
        "WHERE p.id = ?", (player_id,),
    ).fetchone()
    if p is None:
        raise LookupError(f"no player {player_id}")

    next_gw = expected_points(conn, player_id, n_gw=1, from_event=event)
    window = expected_points_window(conn, player_id, _WINDOW_GW, from_event=event)
    parts = next_gw.components
    probs = next_gw.outcome_probs
    minutes = p["minutes"] or 0
    per90 = (lambda v: round(v / minutes * 90, 2) if v is not None and minutes >= 90 else None)
    fixtures = fixture_context_by_team_code(conn, {p["team_id"]}, n_gw=_WINDOW_GW).get(str(p["team_code"]), [])
    pid = {player_id}
    price = p["now_cost"] / 10 if p["now_cost"] is not None else None
    return {
        "player_id": player_id, "name": p["web_name"],
        "full_name": " ".join(x for x in (p["first_name"], p["second_name"]) if x) or p["web_name"],
        "team_id": p["team_id"], "team_name": p["team_name"], "team_short": p["team_short"], "team_code": p["team_code"],
        "position": p["position"], "status": p["status"], "news": p["news"] or None, "chance": p["chance"],
        "is_mine": player_id in mine, "price": price, "owned": p["owned"],
        "xp_next": round(next_gw.median, 2), "floor": round(next_gw.floor, 2), "ceiling": round(next_gw.ceiling, 2),
        "xp_window": round(window.total_median, 2), "fixture_count": window.fixture_count,
        "expected_minutes": round(next_gw.expected_minutes, 0),
        "p_blank": round(probs.prob_blank, 3) if probs else None,
        "p_5plus": round(probs.prob_5plus, 3) if probs else None,
        "components": (
            {k: round(getattr(parts, k), 2) for k in ("appearance", "goals", "assists", "bonus", "clean_sheet", "cards", "conceded", "defcon")}
            if parts else None
        ),
        "points_per_pound": round(window.total_median / price, 2) if price else None,
        "form": float(p["form"]) if p["form"] is not None else None,
        "ppg": float(p["points_per_game"]) if p["points_per_game"] is not None else None,
        "total_points": p["total_points"], "minutes": minutes, "starts": p["starts"],
        "goals": p["goals_scored"], "assists": p["assists"], "xg": p["expected_goals"], "xa": p["expected_assists"],
        "xg90": per90(p["expected_goals"]), "xa90": per90(p["expected_assists"]),
        "start_percent": _start_percents(conn, pid).get(player_id),
        "solio_next": _solio_next(conn, pid).get(player_id),
        "price_trend": _price_trends(conn, pid).get(player_id, "STABLE"),
        "duties": _set_piece_duties(conn, pid).get(player_id, []),
        "fixtures": fixtures,
    }


# label, key, higher is better, number format
_ROWS = (
    ("xP next gameweek", "xp_next", True, "{:.1f}"),
    ("xP next five gameweeks", "xp_window", True, "{:.1f}"),
    ("Floor (10th percentile)", "floor", True, "{:.1f}"),
    ("Ceiling (90th percentile)", "ceiling", True, "{:.1f}"),
    ("Chance of a blank", "p_blank", False, "{:.0%}"),
    ("Chance of 5+ points", "p_5plus", True, "{:.0%}"),
    ("Expected minutes", "expected_minutes", True, "{:.0f}"),
    ("Price (£m)", "price", False, "{:.1f}"),
    ("xP over five per £m", "points_per_pound", True, "{:.2f}"),
    ("Form", "form", True, "{:.1f}"),
    ("Points per game", "ppg", True, "{:.1f}"),
    ("xG per 90", "xg90", True, "{:.2f}"),
    ("xA per 90", "xa90", True, "{:.2f}"),
    ("Owned by (%)", "owned", None, "{:.1f}"),
)


def _rows(a: dict, b: dict) -> list[dict]:
    out = []
    for label, key, higher, fmt in _ROWS:
        va, vb = a.get(key), b.get(key)
        side = None
        if higher is not None and va is not None and vb is not None and va != vb:
            side = "a" if (va > vb) == higher else "b"
        out.append({
            "label": label, "key": key, "a": va, "b": vb, "winner": side,
            "a_text": fmt.format(va) if va is not None else None, "b_text": fmt.format(vb) if vb is not None else None,
        })
    return out


_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_SECONDS = 300.0


def build_compare_payload(ctx: DashboardContext, params: dict | None = None) -> dict:
    """Each request opens a fresh connection and the team-strength fit is cached
    per connection, so an uncached comparison costs about 3s. Five minutes of
    memory per pair makes switching back and forth instant."""
    import time

    key = (params or {}).get("a"), (params or {}).get("b"), tuple(sorted(ctx.squad_ids or ()))
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    payload = _build_compare(ctx, params)
    _CACHE[key] = (time.monotonic(), payload)
    if len(_CACHE) > 64:
        _CACHE.pop(next(iter(_CACHE)))
    return payload


def _build_compare(ctx: DashboardContext, params: dict | None = None) -> dict:
    from fpl_agent.database.connection import get_connection

    params = params or {}
    try:
        a_id, b_id = int(params["a"]), int(params["b"])
    except (KeyError, ValueError):
        raise LookupError("compare needs two player ids, a and b") from None

    conn = get_connection()
    try:
        event = _next_event(conn)
        mine = set(ctx.squad_ids or set())
        a, b = _player(conn, a_id, event, mine), _player(conn, b_id, event, mine)
        try:
            from fpl_agent.models.materiality import transfer_materiality_bar

            mae = transfer_materiality_bar(conn, horizon_gw=_WINDOW_GW).mae
        except Exception:
            mae = None
        payload = {
            "event": event, "window": _WINDOW_GW, "a": a, "b": b, "rows": _rows(a, b),
            "gap_window": round(a["xp_window"] - b["xp_window"], 2),
            "gap_next": round(a["xp_next"] - b["xp_next"], 2),
            "price_gap": round(a["price"] - b["price"], 1) if a["price"] is not None and b["price"] is not None else None,
            "model_mae": mae,
        }
        return attach_photo_codes(conn, payload)
    finally:
        conn.close()


build_compare_payload.needs_context = False


_PROJECTION_CACHE: dict[tuple, tuple[float, dict]] = {}


def build_projection_payload(ctx: DashboardContext, params: dict | None = None) -> dict:
    """One player's forward-looking line for his profile page: the same
    projection the comparison uses, cached five minutes per player for the same
    reason (a fresh connection refits team strength, about 3s)."""
    import time

    from fpl_agent.database.connection import get_connection

    try:
        player_id = int((params or {})["id"])
    except (KeyError, ValueError):
        raise LookupError("projection needs a player id") from None
    key = (player_id, tuple(sorted(ctx.squad_ids or ())))
    hit = _PROJECTION_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    conn = get_connection()
    try:
        event = _next_event(conn)
        payload = {"event": event, "window": _WINDOW_GW, "player": _player(conn, player_id, event, set(ctx.squad_ids or ()))}
    finally:
        conn.close()
    _PROJECTION_CACHE[key] = (time.monotonic(), payload)
    if len(_PROJECTION_CACHE) > 128:
        _PROJECTION_CACHE.pop(next(iter(_PROJECTION_CACHE)))
    return payload


build_projection_payload.needs_context = False
