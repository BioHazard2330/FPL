"""MY TEAM screen JSON payload (2026-09-08, Phase 8.2 Stage 3). Reads the
same real fields `monitoring/dashboard/myteam.py`/`legacy.py::
_pitch_html_from_xi` already render as HTML - team codes, lineup states, the
CORE/WEAK_LINK/MINUTES_RISK tier classification - never a second projection
pass.

Deliberately scoped out of this first pass, disclosed rather than silently
dropped: the per-player Player Inspector drawer (tooltip football/market
signal, ACTUAL/LIVE-vs-NEXT point states, next-fixture difficulty). Those
need their own real per-player Solio/football-intelligence reads
(`_market_signal_for`/`_football_signal_for` in `legacy.py`) - a genuinely
separate, bounded-cost feature, not required for the pitch itself to be
real and correct. The projected-future-squad switcher (`squad.py`) is
likewise not in this payload yet - CURRENT squad only for now."""
from fpl_agent.monitoring.dashboard.context import DashboardContext

_WEAK_LINK_FLOOR_XP = 3.0
_MINUTES_RISK_FLOOR = 60.0
_POSITION_ORDER = ["GKP", "DEF", "MID", "FWD"]
_LINEUP_LABEL = {
    "CONFIRMED_STARTING": "Confirmed",
    "PREDICTED_START": "Predicted",
    "CONFIRMED_BENCHED": "Benched",
    "OUT_UNAVAILABLE": "Out",
}


def _player_json(c, *, team_code: int | None, is_captain: bool, is_vice: bool, tier: str | None, lineup) -> dict:
    lineup_json = None
    if lineup is not None and lineup.state != "UNKNOWN":
        lineup_json = {
            "state": lineup.state,
            "label": _LINEUP_LABEL.get(lineup.state, lineup.state.replace("_", " ").title()),
            "detail": lineup.detail,
        }
    return {
        "player_id": c.player_id,
        "name": c.web_name,
        "position": c.position,
        "team_short": c.team_short,
        "team_code": team_code,
        "price_m": round(c.price_tenths / 10, 1),
        "median": round(c.median, 2),
        "floor": round(c.floor, 2),
        "ceiling": round(c.ceiling, 2),
        "expected_minutes": round(c.expected_minutes, 0) if c.expected_minutes is not None else None,
        "confidence": c.confidence,
        "is_captain": is_captain,
        "is_vice": is_vice,
        "tier": tier,
        "lineup": lineup_json,
    }


def build_my_team_payload(ctx: DashboardContext) -> dict:
    xi = ctx.display_xi
    if xi is None or not xi.starting:
        return {
            "has_squad": False,
            "error": ctx.squad_error_html or "No locked squad to show yet.",
            "bar": {"squad_value_m": ctx.squad_value_m, "bank_m": ctx.bank_m},
        }

    # Real per-player team code + lineup state - computed once in
    # `build_dashboard_context` itself (`ctx.team_codes`/`ctx.
    # squad_lineup_by_id`), never a second live `conn` opened here. Payload
    # builders only ever take the already-built `ctx`, matching
    # `command_payload.py`'s own established boundary.
    team_codes = ctx.team_codes
    lineup_by_id = ctx.squad_lineup_by_id

    tier_by_id: dict[int, str] = {}
    if xi.starting:
        top = max(xi.starting, key=lambda c: c.median)
        tier_by_id[top.player_id] = "CORE"
        for c in xi.starting:
            if c.player_id in tier_by_id:
                continue
            if c.median < _WEAK_LINK_FLOOR_XP:
                tier_by_id[c.player_id] = "WEAK_LINK"
            elif c.expected_minutes is not None and c.expected_minutes < _MINUTES_RISK_FLOOR:
                tier_by_id[c.player_id] = "MINUTES_RISK"

    def _to_json(c) -> dict:
        return _player_json(
            c, team_code=team_codes.get(c.team_id), is_captain=c.player_id == ctx.cap_id,
            is_vice=c.player_id == ctx.vc_id, tier=tier_by_id.get(c.player_id), lineup=lineup_by_id.get(c.player_id),
        )

    by_position: dict[str, list[dict]] = {p: [] for p in _POSITION_ORDER}
    for c in xi.starting:
        by_position.setdefault(c.position, []).append(_to_json(c))
    formation = "-".join(str(len(by_position[p])) for p in ("DEF", "MID", "FWD"))

    ranked = sorted(xi.starting, key=lambda c: c.median)
    weak_links = [
        {"name": c.web_name, "team_short": c.team_short, "median": round(c.median, 1), "expected_minutes": c.expected_minutes}
        for c in ranked[:3] if c.median < _WEAK_LINK_FLOOR_XP
    ]
    top = max(xi.starting, key=lambda c: c.median)
    strong_link = {"name": top.web_name, "team_short": top.team_short, "median": round(top.median, 1), "expected_minutes": top.expected_minutes}

    return {
        "has_squad": True,
        "bar": {
            "squad_value_m": ctx.squad_value_m,
            "bank_m": ctx.bank_m,
            "formation": formation,
            "captain_name": ctx.captain_name,
            "vice_name": ctx.vice_name,
            "headline_xp": ctx.headline_xp,
            "xp_summary_label": ctx.xp_summary_label,
            "actual_points_label": ctx.actual_points_label,
            "pitch_heading": ctx.pitch_heading,
        },
        "risks": ctx.risks_list or [],
        "positions": [{"position": p, "label": p, "players": by_position[p]} for p in _POSITION_ORDER if by_position[p]],
        "bench": [_to_json(c) for c in xi.bench],
        "weak_links": weak_links,
        "strong_link": strong_link,
    }
