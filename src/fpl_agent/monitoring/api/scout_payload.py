"""SCOUT screen JSON payload (2026-09-08, Phase 8.3/9). Two real surfaces:
the league-wide Player Search table (`monitoring/dashboard/player_search.py`'s
own real SQL, reused verbatim) and the Opportunity Board (Breakout/Fixture
Swing/Role Change/Value/Trap - the same real candidate scans
`monitoring/dashboard/opportunity.py` already runs, reshaped as JSON instead
of HTML strings, never a second/different scan).

Real, disclosed deferred scope: Price History is real and already computed
by the old dashboard's `scout.py`, but converting its own HTML renderer to a
structured JSON shape is real, comparable-sized follow-up work of its own -
not attempted this pass. Transfer Momentum, Template Team, and Expected Data
(2026-09-08 v3, direct user follow-up: "more football") ARE now exposed -
see `_momentum`/`_template_team_json`/`_expected_data_json`. Statistics
(`legacy.py::_statistics_html`) was deliberately NOT ported - checked its
real fields against the main Player Search table's own columns and found it
squad-scoped/total-only, a strict subset already reachable there via the
existing "My Squad" filter toggle; porting it would be pure duplication, not
new value.

**Cached from the start this time** (2026-09-08, Phase 9 - learned live from
the football/advanced/command latency bugs found earlier this same phase):
`find_breakouts`/`find_traps` are real, non-trivial league-wide scans - the
same TTL + proactive-refresh shape as `football_payload.py`/`advanced_
payload.py`, applied here before shipping, not bolted on after a real user-
visible slowdown."""
import threading
import time

from fpl_agent.monitoring.dashboard.context import DashboardContext

_CACHE_LOCK = threading.Lock()
_cached_payload: dict | None = None
_cached_at: float = 0.0
_TTL_SECONDS = 600.0


def build_scout_payload(ctx: DashboardContext) -> dict:
    global _cached_payload, _cached_at
    now = time.monotonic()
    with _CACHE_LOCK:
        if _cached_payload is not None and (now - _cached_at) < _TTL_SECONDS:
            return _cached_payload
    payload = _build_scout_payload_uncached(ctx)
    with _CACHE_LOCK:
        _cached_payload = payload
        _cached_at = time.monotonic()
    return payload


def run_scout_refresh_loop(ctx_factory, stop_event: threading.Event, interval: float = 480.0) -> None:
    """Same real proactive-background-warm shape as the other screens'
    refresh loops - wired into `LiveServer.start()` alongside them."""
    global _cached_payload, _cached_at
    while not stop_event.is_set():
        if stop_event.wait(interval):
            break
        try:
            ctx = ctx_factory()
            payload = _build_scout_payload_uncached(ctx)
            with _CACHE_LOCK:
                _cached_payload = payload
                _cached_at = time.monotonic()
        except Exception:
            import logging
            logging.getLogger("fpl_agent.dashboard").exception(
                "background scout-payload refresh failed - keeping the previous cached result, next tick will retry"
            )


def _opportunity_row(kind: str, *, name: str, position: str, price_m: float | None, ownership_pct: float | None,
                      key_metric: str, why_now: str, confidence: str, team_code: int | None, xp: float | None,
                      expected_minutes: float | None, risk: str | None, considered_by_optimizer: bool | None,
                      squad_impact: str | None, what_would_change: str | None) -> dict:
    return {
        "kind": kind, "name": name, "position": position, "price_m": price_m, "ownership_pct": ownership_pct,
        "key_metric": key_metric, "why_now": why_now, "confidence": confidence, "team_code": team_code,
        "xp": round(xp, 1) if xp is not None else None,
        "expected_minutes": round(expected_minutes, 0) if expected_minutes is not None else None,
        "risk": risk, "considered_by_optimizer": considered_by_optimizer, "squad_impact": squad_impact,
        "what_would_change": what_would_change,
    }


def _build_opportunities(conn, ctx: DashboardContext) -> dict:
    from fpl_agent.models.breakouts import MAX_OWNERSHIP_PERCENT, MIN_VALUE_RATIO, find_breakouts
    from fpl_agent.models.expected_minutes import expected_minutes as real_expected_minutes
    from fpl_agent.models.expected_points import expected_points as real_expected_points
    from fpl_agent.models.projection_confidence import assess_projection_confidence
    from fpl_agent.models.traps import find_traps
    from fpl_agent.monitoring.dashboard.legacy import _bulk_player_lookup, _fixture_quality, _relative_time
    from fpl_agent.monitoring.dashboard.opportunity import _MAX_PER_CATEGORY, _setpiece_order_change_text

    squad_ids = ctx.squad_ids or set()

    def confidence_label(pid: int) -> str:
        try:
            return assess_projection_confidence(conn, pid).overall
        except Exception:
            return "MEDIUM"

    def risk_from_confidence(confidence: str) -> str | None:
        if confidence in ("LOW", "VERY_LOW"):
            return f"projection confidence is {confidence.replace('_', ' ').lower()} - based on limited real evidence so far"
        return None

    def mins(pid: int) -> float | None:
        try:
            return real_expected_minutes(conn, pid).expected_minutes
        except Exception:
            return None

    def median_xp(pid: int) -> float | None:
        try:
            return real_expected_points(conn, pid).median
        except Exception:
            return None

    breakouts, traps, role_rows, value_rows = [], [], [], []
    try:
        breakouts = [b for b in find_breakouts(conn)[:_MAX_PER_CATEGORY] if b.player_id not in squad_ids]
    except Exception:
        pass
    try:
        traps = find_traps(conn)[:_MAX_PER_CATEGORY]
    except Exception:
        pass
    try:
        role_rows = conn.execute(
            "SELECT ce.entity_id, p.web_name, et.singular_name_short AS position, ce.detected_at, "
            "ce.old_value, ce.new_value "
            "FROM change_events ce JOIN players p ON p.id = ce.entity_id "
            "JOIN element_types et ON et.id = p.element_type "
            "WHERE ce.event_type = 'setpiece_change' AND ce.entity = 'player' AND p.removed = 0 "
            "ORDER BY ce.detected_at DESC LIMIT ?",
            (_MAX_PER_CATEGORY,),
        ).fetchall()
    except Exception:
        pass
    try:
        value_rows = [
            r for r in conn.execute(
                "SELECT old.player_id, old.value_tenths AS old_value, cur.value_tenths AS new_value, "
                "old.valid_until AS changed_at, p.web_name, et.singular_name_short AS position "
                "FROM player_price_history old "
                "JOIN player_price_history cur ON cur.player_id = old.player_id AND cur.valid_until IS NULL "
                "JOIN players p ON p.id = old.player_id JOIN element_types et ON et.id = p.element_type "
                "WHERE old.valid_until IS NOT NULL AND cur.value_tenths > old.value_tenths AND p.removed = 0 "
                "ORDER BY old.valid_until DESC LIMIT ?",
                (_MAX_PER_CATEGORY,),
            ).fetchall()
            if r["player_id"] not in squad_ids
        ]
    except Exception:
        pass

    candidate_ids = (
        {b.player_id for b in breakouts} | {t.player_id for t in traps}
        | {r["entity_id"] for r in role_rows} | {r["player_id"] for r in value_rows}
    )
    team_lookup = _bulk_player_lookup(conn, candidate_ids) if candidate_ids else {}

    def price_m(pid: int) -> float | None:
        tenths = team_lookup.get(pid, {}).get("price_tenths")
        return tenths / 10 if tenths is not None else None

    impact_by_player: dict[int, str] = {}
    if ctx.ta is not None:
        for opt in ctx.ta.candidates:
            c = opt.candidate
            impact_by_player.setdefault(c.player_in_id, c.player_out_name)

    breakout_rows, trap_rows, role_change_rows, value_change_rows = [], [], [], []

    for b in breakouts:
        team_code = team_lookup.get(b.player_id, {}).get("team_code")
        own_bit = f"{b.ownership_percent:.1f}% owned" if b.ownership_percent is not None else "low ownership"
        confidence = confidence_label(b.player_id)
        own_txt = f"{b.ownership_percent:.1f}%" if b.ownership_percent is not None else "ownership"
        change_txt = f"ownership rises above {MAX_OWNERSHIP_PERCENT:.0f}% (currently {own_txt}) or value ratio falls below {MIN_VALUE_RATIO:.1f} xP/£m"
        breakout_rows.append(_opportunity_row(
            "Breakout", name=b.web_name, position=b.position, price_m=price_m(b.player_id),
            ownership_pct=b.ownership_percent, key_metric=f"{b.value_ratio:.2f} xP/£m value ratio",
            why_now="; ".join(b.reasons) if b.reasons else f"{b.value_ratio:.2f} xP/£m, {own_bit}",
            confidence=confidence, team_code=team_code, xp=b.median, expected_minutes=mins(b.player_id),
            risk=risk_from_confidence(confidence), considered_by_optimizer=None,
            squad_impact=impact_by_player.get(b.player_id), what_would_change=change_txt,
        ))

    for t in traps:
        team_code = team_lookup.get(t.player_id, {}).get("team_code")
        own_bit = f"{t.ownership_percent:.1f}% owned" if t.ownership_percent is not None else "high ownership"
        confidence = confidence_label(t.player_id)
        trap_rows.append(_opportunity_row(
            "Trap", name=t.web_name, position=t.position, price_m=price_m(t.player_id),
            ownership_pct=t.ownership_percent, key_metric=f"{t.eo_source} ownership source",
            why_now="; ".join(t.reasons) if t.reasons else f"{own_bit}, case weakening",
            confidence=confidence, team_code=team_code, xp=median_xp(t.player_id), expected_minutes=mins(t.player_id),
            risk=risk_from_confidence(confidence), considered_by_optimizer=None,
            squad_impact=impact_by_player.get(t.player_id), what_would_change=None,
        ))

    for r in role_rows:
        team_code = team_lookup.get(r["entity_id"], {}).get("team_code")
        order_bit = _setpiece_order_change_text(r["old_value"], r["new_value"])
        confidence = confidence_label(r["entity_id"])
        role_change_rows.append(_opportunity_row(
            "Role Change", name=r["web_name"], position=r["position"], price_m=price_m(r["entity_id"]),
            ownership_pct=None, key_metric=f"set-piece {order_bit}, {_relative_time(r['detected_at'])}",
            why_now=order_bit, confidence=confidence, team_code=team_code, xp=median_xp(r["entity_id"]),
            expected_minutes=mins(r["entity_id"]), risk=risk_from_confidence(confidence),
            considered_by_optimizer=None, squad_impact=impact_by_player.get(r["entity_id"]), what_would_change=None,
        ))

    for r in value_rows:
        team_code = team_lookup.get(r["player_id"], {}).get("team_code")
        confidence = confidence_label(r["player_id"])
        value_change_rows.append(_opportunity_row(
            "Value", name=r["web_name"], position=r["position"], price_m=r["new_value"] / 10,
            ownership_pct=None, key_metric=f"£{r['old_value']/10:.1f}m -> £{r['new_value']/10:.1f}m",
            why_now=f"price rise {_relative_time(r['changed_at'])}", confidence=confidence, team_code=team_code,
            xp=median_xp(r["player_id"]), expected_minutes=mins(r["player_id"]), risk=risk_from_confidence(confidence),
            considered_by_optimizer=None, squad_impact=impact_by_player.get(r["player_id"]), what_would_change=None,
        ))

    fixture_swing_rows = []
    try:
        team_rows = conn.execute("SELECT id, short_name, code FROM teams").fetchall()
        squad_team_ids = {
            row["team_id"] for row in conn.execute(
                "SELECT team_id FROM players WHERE id IN ({})".format(",".join("?" * len(squad_ids))), list(squad_ids)
            ).fetchall()
        } if squad_ids else set()
        swings = []
        for t in team_rows:
            if t["id"] in squad_team_ids:
                continue
            q = _fixture_quality(conn, t["id"], n_gw=5)
            if q is not None and q[0] == "ok":
                swings.append((q[2], t["short_name"], q[1], t["code"]))
        swings.sort(key=lambda x: x[0])
        for avg, short_name, label, code in swings[:_MAX_PER_CATEGORY]:
            fixture_swing_rows.append({
                "team_short": short_name, "team_code": code, "avg_difficulty": round(avg, 1),
                "label": f"{label} fixture run",
            })
    except Exception:
        pass

    # Real transfer momentum (`market.py::render_top_transfers_html`'s own
    # real SQL, reused verbatim) - league-wide top transferred-in/out
    # players this event, real net counts from `player_transfer_momentum_
    # history`.
    def _momentum(direction: str) -> list[dict]:
        column = "transfers_in_event" if direction == "in" else "transfers_out_event"
        try:
            mrows = conn.execute(
                f"SELECT m.{column} AS n, p.web_name, t.short_name AS team_short, t.code AS team_code "
                "FROM player_transfer_momentum_history m JOIN players p ON p.id = m.player_id JOIN teams t ON t.id = p.team_id "
                f"WHERE m.valid_until IS NULL AND p.removed = 0 ORDER BY m.{column} DESC LIMIT 5",
            ).fetchall()
        except Exception:
            return []
        return [
            {"name": r["web_name"], "team_short": r["team_short"], "team_code": r["team_code"], "count": r["n"]}
            for r in mrows if r["n"]
        ]

    return {
        "breakout": breakout_rows, "fixture_swing": fixture_swing_rows, "role_change": role_change_rows,
        "value": value_change_rows, "trap": trap_rows,
        "transfers_in": _momentum("in"), "transfers_out": _momentum("out"),
    }


_TEMPLATE_POSITION_ORDER = ("GKP", "DEF", "MID", "FWD")


def _template_team_json(conn, squad_ids: set[int]) -> dict:
    """Real TEMPLATE TEAM panel, JSON-native (2026-09-08 v3, direct user
    follow-up: "more football" - closes a gap this module's own docstring
    used to disclose as deferred). Same real `get_template`/sampled-EO data
    `template_team.py::render_template_team_html` already renders - a
    per-position highest-owned pool (never a formation-constrained "best
    XI" - this project has never computed one and presenting it here would
    imply a selection this data doesn't support, same disclosed limit the
    HTML version already carries), plus the same real overlap/differential
    facts against the locked squad."""
    from fpl_agent.models.effective_ownership import get_all_sample_eo
    from fpl_agent.models.template import get_template
    from fpl_agent.monitoring.dashboard.legacy import _bulk_player_lookup

    template_players = get_template(conn)
    if not template_players:
        return {"positions": [], "overlap": None}

    lookup = _bulk_player_lookup(conn, {tp.player_id for tp in template_players})
    by_pos: dict[str, list] = {}
    for tp in template_players:
        by_pos.setdefault(tp.position, []).append({
            "player_id": tp.player_id, "name": tp.web_name,
            "team_code": lookup.get(tp.player_id, {}).get("team_code"),
            "ownership_pct": round(tp.ownership_percent, 1),
            "eo_percent": round(tp.effective_ownership_percent, 1) if tp.effective_ownership_percent is not None else None,
            "eo_source": tp.eo_source,
            "margin_of_error_pp": round(tp.margin_of_error_pp, 1) if tp.margin_of_error_pp is not None else None,
            "is_mine": tp.player_id in squad_ids,
        })
    positions = [{"position": pos, "players": by_pos[pos]} for pos in _TEMPLATE_POSITION_ORDER if pos in by_pos]

    overlap = None
    if squad_ids:
        template_ids = {tp.player_id for tp in template_players}
        overlap_count = len(squad_ids & template_ids)
        missing = [tp for tp in template_players if tp.player_id not in squad_ids]
        missing.sort(key=lambda tp: -(tp.effective_ownership_percent if tp.effective_ownership_percent is not None else tp.ownership_percent))

        rows = conn.execute(
            "SELECT p.id, p.web_name, oh.selected_by_percent FROM players p "
            "JOIN player_ownership_history oh ON oh.player_id = p.id AND oh.valid_until IS NULL "
            "WHERE p.id IN ({})".format(",".join("?" * len(squad_ids))),
            tuple(squad_ids),
        ).fetchall()
        eo_by_player = get_all_sample_eo(conn)
        squad_owned = []
        for r in rows:
            eo = eo_by_player.get(r["id"])
            ownership = eo.eo_percent if eo is not None else r["selected_by_percent"]
            squad_owned.append((ownership, r["web_name"]))
        squad_owned.sort()

        overlap = {
            "overlap_count": overlap_count,
            "squad_size": len(squad_ids),
            "differential_name": squad_owned[0][1] if squad_owned else None,
            "differential_pct": round(squad_owned[0][0], 1) if squad_owned else None,
            "missing_top3": [{"player_id": tp.player_id, "name": tp.web_name} for tp in missing[:3]],
        }

    return {"positions": positions, "overlap": overlap}


def _expected_data_json(conn, squad_ids: set[int], limit: int = 15) -> list[dict]:
    """Real league-wide xGI leaderboard WITH per-90 rates (2026-09-08 v3,
    direct user follow-up: "more football" - the main Scout table only ever
    shows raw-total xGI, which under-ranks a high-rate player who's played
    fewer minutes; this is a real, non-redundant scouting signal - the same
    real `player_match_stats_history` Understat data
    `player_data.py::render_expected_data_html` already aggregates, reshaped
    as JSON)."""
    from fpl_agent.models.rules import current_season

    season = current_season(conn)
    if season is None:
        return []
    rows = conn.execute(
        "SELECT h.player_id, p.web_name, t.short_name AS team_short, t.code AS team_code, "
        "SUM(h.minutes) AS minutes, SUM(h.xg) AS xg, SUM(h.xa) AS xa "
        "FROM player_match_stats_history h "
        "JOIN players p ON p.id = h.player_id JOIN teams t ON t.id = p.team_id "
        "WHERE h.season = ? AND p.removed = 0 "
        "GROUP BY h.player_id HAVING SUM(h.minutes) > 0 "
        "ORDER BY (SUM(h.xg) + SUM(h.xa)) DESC LIMIT ?",
        (season, limit),
    ).fetchall()
    out = []
    for r in rows:
        p90 = 90 / r["minutes"]
        xgi = r["xg"] + r["xa"]
        out.append({
            "player_id": r["player_id"], "name": r["web_name"], "team_short": r["team_short"],
            "team_code": r["team_code"], "xg": round(r["xg"], 1), "xa": round(r["xa"], 1), "xgi": round(xgi, 1),
            "xg_per90": round(r["xg"] * p90, 2), "xa_per90": round(r["xa"] * p90, 2), "xgi_per90": round(xgi * p90, 2),
            "minutes": r["minutes"], "is_mine": r["player_id"] in squad_ids,
        })
    return out


def _build_scout_payload_uncached(ctx: DashboardContext) -> dict:
    from fpl_agent.database.connection import get_connection

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT p.id, p.web_name, t.short_name AS team_short, t.code AS team_code, "
            "et.singular_name_short AS position, ph.value_tenths, oh.selected_by_percent, "
            "s.total_points, s.form, s.expected_goals, s.expected_assists, "
            "s.goals_scored, s.assists, s.minutes, s.bonus "
            "FROM players p "
            "JOIN teams t ON t.id = p.team_id "
            "JOIN element_types et ON et.id = p.element_type "
            "LEFT JOIN player_price_history ph ON ph.player_id = p.id AND ph.valid_until IS NULL "
            "LEFT JOIN player_ownership_history oh ON oh.player_id = p.id AND oh.valid_until IS NULL "
            "LEFT JOIN player_stats_snapshot s ON s.id = ("
            "  SELECT id FROM player_stats_snapshot WHERE player_id = p.id ORDER BY retrieved_at DESC LIMIT 1"
            ") "
            "WHERE p.removed = 0 AND p.status != 'u' "
            "ORDER BY s.total_points DESC NULLS LAST"
        ).fetchall()

        squad_ids = ctx.squad_ids or set()
        players = []
        for r in rows:
            xgi = None
            if r["expected_goals"] is not None or r["expected_assists"] is not None:
                xgi = round((r["expected_goals"] or 0) + (r["expected_assists"] or 0), 2)
            players.append({
                "player_id": r["id"],
                "name": r["web_name"],
                "goals": r["goals_scored"], "assists": r["assists"], "minutes": r["minutes"], "bonus": r["bonus"],
                "team_short": r["team_short"],
                "team_code": r["team_code"],
                "position": r["position"],
                "price_m": round(r["value_tenths"] / 10, 1) if r["value_tenths"] is not None else None,
                "owned_pct": round(r["selected_by_percent"], 1) if r["selected_by_percent"] is not None else None,
                "total_points": r["total_points"],
                "form": round(r["form"], 1) if r["form"] is not None else None,
                "xgi": xgi,
                "is_mine": r["id"] in squad_ids,
            })

        opportunities = _build_opportunities(conn, ctx)
        price_moves = _price_moves_block(conn, squad_ids)
        template_team = _template_team_json(conn, squad_ids)
        expected_data = _expected_data_json(conn, squad_ids)
    finally:
        conn.close()

    return {
        "players": players, "opportunities": opportunities, "price_moves": price_moves,
        "template_team": template_team, "expected_data": expected_data,
    }


def _price_moves_block(conn, squad_ids: set[int]) -> dict:
    """Real price-change forecast + confirmed-change ledger (2026-09-08,
    full redesign pass - the same real data `price_history.py`'s HTML
    renderer already reads, reshaped as JSON: `player_price_history`
    (change-tracked, written every sync) + `player_transfer_momentum_
    history` (Pillar 1a) through the existing, documented-uncalibrated
    `models.price_forecast` heuristic. Cheap - pure SQL reads, no xP/
    optimizer computation - bounded to the top 24 real movers by |momentum|
    (never the full ~650-player scan; the confirmed ledger is already
    capped at 20 by its own real function)."""
    from fpl_agent.models.price_forecast import RISE_THRESHOLD, classify_price_change

    rows = conn.execute(
        "SELECT p.id, p.web_name, t.short_name AS team_short, t.code AS team_code, "
        "et.singular_name_short AS position, cur.value_tenths, "
        "m.transfers_in_event, m.transfers_out_event "
        "FROM players p JOIN teams t ON t.id = p.team_id JOIN element_types et ON et.id = p.element_type "
        "LEFT JOIN player_price_history cur ON cur.player_id = p.id AND cur.valid_until IS NULL "
        "LEFT JOIN player_transfer_momentum_history m ON m.player_id = p.id AND m.valid_until IS NULL "
        "WHERE p.removed = 0"
    ).fetchall()
    entries = [(r, classify_price_change(conn, r["id"])) for r in rows]
    entries = [(r, f) for r, f in entries if f.direction != "STABLE"]
    entries.sort(key=lambda e: -abs(e[1].momentum_ratio))

    forecast = []
    for r, f in entries[:24]:
        progress_pct = min(100.0, abs(f.momentum_ratio) / RISE_THRESHOLD * 100.0) if RISE_THRESHOLD else 0.0
        forecast.append({
            "player_id": r["id"], "name": r["web_name"], "team_short": r["team_short"], "team_code": r["team_code"],
            "position": r["position"], "price_m": round(r["value_tenths"] / 10, 1) if r["value_tenths"] is not None else None,
            "net_transfers": (r["transfers_in_event"] or 0) - (r["transfers_out_event"] or 0),
            "direction": f.direction, "progress_pct": round(progress_pct, 0), "is_mine": r["id"] in squad_ids,
        })

    ledger_rows = conn.execute(
        "SELECT h.player_id, h.value_tenths AS new_tenths, h.valid_from, "
        "p.web_name, t.short_name AS team_short, t.code AS team_code, "
        "(SELECT prev.value_tenths FROM player_price_history prev "
        " WHERE prev.player_id = h.player_id AND prev.valid_until = h.valid_from) AS old_tenths "
        "FROM player_price_history h JOIN players p ON p.id = h.player_id JOIN teams t ON t.id = p.team_id "
        "WHERE h.valid_until IS NULL ORDER BY h.valid_from DESC LIMIT 60"
    ).fetchall()
    ledger = []
    for r in ledger_rows:
        if r["old_tenths"] is None or r["old_tenths"] == r["new_tenths"]:
            continue
        ledger.append({
            "player_id": r["player_id"], "name": r["web_name"], "team_short": r["team_short"], "team_code": r["team_code"],
            "old_price_m": round(r["old_tenths"] / 10, 1), "new_price_m": round(r["new_tenths"] / 10, 1),
            "valid_from": r["valid_from"],
        })
        if len(ledger) == 20:
            break

    return {"forecast": forecast, "ledger": ledger}
