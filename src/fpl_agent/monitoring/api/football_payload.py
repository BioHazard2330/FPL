"""FOOTBALL screen JSON payload (2026-09-08, Phase 8.3). Reads the same real
`squad_football_signals`/`team_outlook`/`_team_recent_form` data `monitoring/
dashboard/football.py` already renders as HTML.

Real, disclosed scope for this pass (matching this project's own "disclosed
partial scope, never faked completeness" discipline): the signals feed and
the team-state table are the two real, primary "football intelligence"
surfaces and are fully covered here. `football.py`'s own MANAGER/XI/
AVAILABILITY changes feed, FIXTURE TICKER, Fixture Projections, Team Odds,
and MATCH EVIDENCE disclosures are NOT yet exposed as JSON - each is real,
already-computed data, but converting their own HTML renderers
(`legacy.py::_squad_changes_html`/`_fixture_projections_html`/`market.py::
render_team_odds_html`/`fixtures.py::render_fixture_tool_html`/`_match_
report_strip_html`) to structured payloads is real, scoped, comparable-sized
follow-up work of its own - the old dashboard stays the complete real
reference for these until then."""
import threading
import time

from fpl_agent.monitoring.dashboard.context import DashboardContext
from fpl_agent.monitoring.dashboard.football import _CATEGORY_PRIORITY, _DECISION_EFFECT_RANK

_CACHE_LOCK = threading.Lock()
_cached_payload: dict | None = None
_cached_at: float = 0.0
_TTL_SECONDS = 600.0

_CATEGORY_LABEL = {
    "SET_PIECE_CHANGE": "Set pieces", "ROLE_CHANGE": "Role change", "TACTICAL_CHANGE": "Tactical",
    "SET_PIECES": "Set pieces", "GOAL_THREAT": "Goal threat", "CREATION": "Creation", "MINUTES": "Minutes",
}


def _signal_json(s, crest_by_team: dict, team_by_player: dict, squad_ids: set[int]) -> dict:
    return {
        "category": s.category,
        "entity_id": s.entity_id,
        "entity_name": s.entity_name,
        "team_code": crest_by_team.get(team_by_player.get(s.entity_id)),
        "evidence": s.evidence,
        "interpretation": s.interpretation,
        "fpl_effect": s.fpl_effect,
        "confidence": s.confidence,
        "direction": s.direction,
        "decision_effect": s.decision_effect,
        "is_mine": s.entity_id in squad_ids,
        "expires_at": s.expires_at,
    }


def build_football_payload(ctx: DashboardContext) -> dict:
    """Real, found-live latency fix (2026-09-08, Phase 9) - this build was
    previously uncached, a real ~10-16s per-request cost (a league-wide
    ~650-player signal scan + 20 real per-team `team_outlook` calls),
    confirmed live during this phase's own visual QA. Same real TTL-cache
    shape as `advanced_payload.py`'s readiness cache - a 10-minute-old
    football-intelligence read is honest, not stale in any way a user would
    notice (this data updates on the same real match-analysis/sync cadence
    every other cached read here does)."""
    global _cached_payload, _cached_at
    now = time.monotonic()
    with _CACHE_LOCK:
        if _cached_payload is not None and (now - _cached_at) < _TTL_SECONDS:
            return _cached_payload
    payload = _build_football_payload_uncached(ctx)
    with _CACHE_LOCK:
        _cached_payload = payload
        _cached_at = time.monotonic()
    return payload


def run_football_refresh_loop(ctx_factory, stop_event: threading.Event, interval: float = 480.0) -> None:
    """Same real proactive-background-warm shape as `context.py::run_
    context_refresh_loop`/`advanced_payload.py::run_readiness_refresh_loop`
    - wired into `LiveServer.start()` alongside them."""
    global _cached_payload, _cached_at
    while not stop_event.is_set():
        if stop_event.wait(interval):
            break
        try:
            ctx = ctx_factory()
            payload = _build_football_payload_uncached(ctx)
            with _CACHE_LOCK:
                _cached_payload = payload
                _cached_at = time.monotonic()
        except Exception:
            import logging
            logging.getLogger("fpl_agent.dashboard").exception(
                "background football-payload refresh failed - keeping the previous cached result, next tick will retry"
            )


def _build_football_payload_uncached(ctx: DashboardContext) -> dict:
    from fpl_agent.database.connection import get_connection
    from fpl_agent.models.football_signal import squad_football_signals
    from fpl_agent.models.team_outlook import team_outlook
    from fpl_agent.monitoring.dashboard.football import _team_recent_form

    conn = get_connection()
    try:
        team_rows = conn.execute("SELECT id, code, short_name FROM teams ORDER BY short_name").fetchall()
        crest_by_team = {r["id"]: r["code"] for r in team_rows}
        player_rows = conn.execute("SELECT id, team_id FROM players WHERE status != 'u'").fetchall()
        player_ids = [r["id"] for r in player_rows]
        team_by_player = {r["id"]: r["team_id"] for r in player_rows}

        try:
            from fpl_agent.optimization.decision_snapshot import build_decision_snapshot
            decision_snapshot = build_decision_snapshot(conn, ca=ctx.ca)
        except Exception:
            decision_snapshot = None
        signals = squad_football_signals(conn, player_ids, lookback=5, decision_snapshot=decision_snapshot) if player_ids else []

        squad_ids = ctx.squad_ids or set()
        by_category: dict[str, list] = {}
        for s in signals:
            by_category.setdefault(s.category, []).append(s)

        categories = []
        for cat in _CATEGORY_PRIORITY:
            rows = by_category.get(cat, [])
            if not rows:
                continue
            ordered = sorted(rows, key=lambda s: s.entity_id not in squad_ids)
            categories.append({
                "category": cat, "label": _CATEGORY_LABEL.get(cat, cat.replace("_", " ").title()),
                "count": len(rows),
                "signals": [_signal_json(s, crest_by_team, team_by_player, squad_ids) for s in ordered[:15]],
            })

        squad_signals = [s for s in signals if s.entity_id in squad_ids]
        richer_player_matches = {
            (s.entity_id, s.match_id) for s in squad_signals if s.category != "MINUTES" and s.match_id is not None
        }
        squad_signals = [
            s for s in squad_signals
            if not (s.category == "MINUTES" and s.direction == "POSITIVE" and (s.entity_id, s.match_id) in richer_player_matches)
        ]
        squad_signals.sort(key=lambda s: _DECISION_EFFECT_RANK.get(s.decision_effect, 0), reverse=True)
        squad_change_signals = [_signal_json(s, crest_by_team, team_by_player, squad_ids) for s in squad_signals[:10]]

        squad_team_ids: set[int] = set()
        if squad_ids:
            squad_team_ids = {
                r["team_id"] for r in conn.execute(
                    "SELECT team_id FROM players WHERE id IN ({})".format(",".join("?" * len(squad_ids))),
                    list(squad_ids),
                ).fetchall()
            }
        team_state = []
        for r in team_rows:
            outlook = team_outlook(conn, r["id"])
            form = _team_recent_form(conn, r["id"], n=3)
            q = outlook.qualitative
            tactical_text = q.current_tactical_signal if q else None
            impact = q.current_fpl_implication if q else None
            if form is None and tactical_text is None and impact is None and outlook.formation is None:
                continue
            team_state.append({
                "team_id": r["id"], "team_code": r["code"], "team_name": outlook.team_name,
                "in_squad": r["id"] in squad_team_ids,
                "attack": {
                    "xg": round(form["xg_for"], 2) if form else None,
                    "shots": round(form["shots_for"], 1) if form and form["shots_for"] is not None else None,
                } if form else None,
                "defence": {
                    "xga": round(form["xg_against"], 2) if form and form["xg_against"] is not None else None,
                    "conceded": round(form["shots_against"], 1) if form and form["shots_against"] is not None else None,
                } if form else None,
                "formation": outlook.formation,
                "tactical": tactical_text,
                "fpl_implication": impact,
                "matches_analyzed": form["n"] if form else 0,
            })
        team_state.sort(key=lambda t: not t["in_squad"])
        team_odds = _team_odds_rows(conn, team_rows)
    finally:
        conn.close()

    return {
        "signal_count": len(signals),
        "squad_signal_count": len(squad_ids & {s.entity_id for s in signals}) if squad_ids else 0,
        "squad_changes": squad_change_signals,
        "categories": categories,
        "team_state": team_state,
        "team_odds": team_odds,
    }


def _team_odds_rows(conn, team_rows) -> list[dict]:
    """Real next-fixture clean-sheet %/projected goals per team, ranked -
    the same real Dixon-Coles/odds-blended numbers `market.py::render_team_
    odds_html` already renders for the old dashboard, reshaped as JSON
    (2026-09-08, full redesign pass - Part 8's own disclosed FOOTBALL gap).
    Cheap: one `team_fixture_ticker(n_gw=1)` + one cached goal read per real
    team, same real cost class the old HTML renderer already pays every
    regen - no new computation, just a JSON shape instead of a table."""
    from fpl_agent.models.blend import clean_sheet_probability
    from fpl_agent.models.fixtures import team_fixture_ticker
    from fpl_agent.monitoring.dashboard.legacy import _cached_fixture_goals_for

    goals_cache: dict = {}
    rows = []
    for t in team_rows:
        tickers = team_fixture_ticker(conn, t["id"], n_gw=1)
        if not tickers:
            continue
        e = tickers[0]
        fixture_row = conn.execute("SELECT * FROM fixtures WHERE id=?", (e.fixture_id,)).fetchone()
        goals_for, goals_against = _cached_fixture_goals_for(conn, fixture_row, t["id"], goals_cache)
        cs = clean_sheet_probability(goals_against)
        rows.append({
            "team_id": t["id"], "team_code": t["code"], "team_short": t["short_name"],
            "opponent_short": e.opponent_short, "is_home": e.is_home,
            "clean_sheet_pct": round(cs * 100, 1), "projected_goals": round(goals_for, 1),
        })
    rows.sort(key=lambda r: -r["clean_sheet_pct"])
    return rows
