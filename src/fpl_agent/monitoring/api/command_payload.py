"""COMMAND screen JSON payload (2026-09-08, Phase 8.2 Stage 2 - the React
frontend's own data source for the decision screen). Reads exactly the same
real fields `monitoring/dashboard/command.py::render_command_screen` already
renders as HTML - reuses that module's own pure helpers (`_gw_num`,
`_horizon_label`) rather than re-deriving them, and never recomputes a
decision. If a field isn't already real and available in `current_rec`/`ta`/
`ca`, it is honestly omitted here too - this module adds no new computation,
only a JSON shape for computation that already exists."""
from fpl_agent.monitoring.dashboard.command import _gw_num, _horizon_label
from fpl_agent.monitoring.dashboard.context import DashboardContext
from fpl_agent.monitoring.dashboard.home import _action_word
from fpl_agent.optimization.captaincy import captain_edge_driver


def _player_brief(option) -> dict:
    """Minimal real player identity + the SAME real median/floor/ceiling
    `expected_points()` already computed for this candidate - never a second
    projection."""
    return {
        "player_id": option.player_id,
        "name": option.web_name,
        "median": round(option.median, 2),
        "floor": round(option.floor, 2) if option.floor is not None else None,
        "ceiling": round(option.ceiling, 2) if option.ceiling is not None else None,
    }


def _captain_block(ca) -> dict | None:
    if ca is None or not ca.options:
        return None
    best = ca.options[0].option
    second = ca.options[1].option if len(ca.options) > 1 else None
    verdict = "KEEP" if ca.decision_kind == "keep" else ("CHANGE" if ca.decision_kind == "change" else "REVIEW")
    verdict_name = best.web_name if ca.decision_kind == "keep" else (ca.suggested.web_name if ca.suggested else best.web_name)
    block = {
        "verdict": verdict,
        "verdict_name": verdict_name,
        "robustness": ca.robustness,
        "best": _player_brief(best),
        "second": _player_brief(second) if second is not None else None,
        "edge": round(best.median - second.median, 2) if second is not None else None,
        "edge_driver": None,
    }
    if second is not None:
        driver = captain_edge_driver(best, second)
        if driver is not None:
            block["edge_driver"] = {"label": driver[0], "value": round(driver[1], 2)}
    return block


def _contribution_block(auth: dict | None, ca) -> list[dict]:
    """Real "WHY THE MODEL PREFERS THIS" rows - see `command.py::
    _contribution_layer_html`'s own docstring for why each of these three is
    mathematically defensible on its own (never an additive decomposition).
    Same >=2-real-rows honesty gate as the HTML version."""
    if not auth:
        return []
    rows = []
    ev = auth.get("nominal_ev_advantage")
    if ev is not None:
        rows.append({"label": "TRANSFER_CHIP_EDGE", "value": round(ev, 2), "unit": "pts"})
    if ca is not None and ca.options and len(ca.options) > 1:
        rows.append({
            "label": "CAPTAIN_EDGE",
            "value": round(ca.options[0].option.median - ca.options[1].option.median, 2),
            "unit": "pts",
        })
    opt_delta = auth.get("optionality_delta")
    if opt_delta is not None:
        rows.append({"label": "OPTIONALITY", "value": opt_delta, "unit": "reachable_states"})
    return rows if len(rows) >= 2 else []


def _checkpoint_block(paths: list[dict] | None, chosen_label: str | None, alt_label: str | None) -> dict | None:
    """Same real `horizon_breakdown` per path PLAN's own trajectory chart
    already computes (`build_diverse_paths`) - zero new search."""
    if not paths:
        return None

    def _find(label):
        if label is None:
            return None
        for p in paths:
            steps = p.get("steps") or []
            if steps and steps[0].get("action") == label:
                return p
        return None

    chosen = _find(chosen_label) or (paths[0] if paths else None)
    alt = _find(alt_label) or next((p for p in paths if p is not chosen), None)
    if chosen is None or alt is None:
        return None
    chosen_bd, alt_bd = chosen.get("horizon_breakdown") or {}, alt.get("horizon_breakdown") or {}
    horizons = sorted(set(chosen_bd) & set(alt_bd))
    if not horizons:
        return None
    return {
        "horizons": horizons,
        "chosen": {
            "name": (chosen.get("steps") or [{}])[0].get("action", "This pick"),
            "totals": [round(chosen_bd[h]["path_total"], 1) for h in horizons],
        },
        "alt": {
            "name": (alt.get("steps") or [{}])[0].get("action", "Alternative"),
            "totals": [round(alt_bd[h]["path_total"], 1) for h in horizons],
        },
        "edge": [round(chosen_bd[h]["path_total"] - alt_bd[h]["path_total"], 1) for h in horizons],
    }


def _alternative_block(auth: dict | None, diag: dict | None) -> dict | None:
    if not auth:
        return None
    alt = auth.get("best_alternative") or ""
    alt_label, _, alt_action = alt.partition(": ")
    if not alt_label:
        return None
    stats = {}
    if diag:
        if diag.get("path_robustness_verdict"):
            stats["robustness"] = diag["path_robustness_verdict"]
        if diag.get("price_robust") is not None:
            stats["price"] = "safe" if diag["price_robust"] else "thin margin"
        if diag.get("credibility_label"):
            stats["credibility"] = diag["credibility_label"].replace("_", " ").title()
    reasons = []
    if diag and diag.get("price_robust") and auth.get("price_robustness") is False:
        reasons.append("safer on price - no thin-margin move")
    if diag and diag.get("path_robustness_verdict") == "ROBUST":
        reasons.append("holds up better under bad luck")
    if diag and diag.get("credibility_label") == "LOW_FRICTION":
        reasons.append("fewer speculative legs")
    return {
        "label": alt_label,
        "action": alt_action,
        "is_chip": alt_action.upper().startswith("PLAY "),
        "reasons": reasons,
        "stats": stats,
    }


def _monitor_block(auth: dict | None) -> list[dict]:
    if not auth:
        return []
    rows = []
    if auth.get("price_robustness") is False:
        rows.append({"current": "PRICE thin margin", "trigger": "target price rises", "consequence": "re-evaluate path"})
    for d in (auth.get("critical_dependencies") or [])[:3]:
        rows.append({"current": d, "trigger": "status or price changes", "consequence": "re-run the plan"})
    ev = auth.get("nominal_ev_advantage")
    alt_label = (auth.get("best_alternative") or "").partition(": ")[0]
    if ev is not None and alt_label:
        rows.append({
            "current": f"ALTERNATIVE -{ev:.1f}pts behind", "trigger": "margin closes",
            "consequence": f"reconsider {alt_label}",
        })
    return rows


def _trajectory_block(auth: dict | None, ca, current_gw_label: str) -> dict | None:
    """Real state-transition scene as data: current squad (top captain
    shortlist shirts, same real `ca.options` the matchup itself reads), the
    action node, and the real future conditional legs with their own fragile-
    dependency flag - matches `command.py::_trajectory_html`'s own real
    fields exactly, no new derivation."""
    if not auth:
        return None
    now_label = auth.get("immediate_action") or ""
    _, _, now_action = now_label.partition(": ")
    now_gw = _gw_num(current_gw_label) or _gw_num(now_action)
    deps = set(auth.get("critical_dependencies") or [])
    fragile = auth.get("robustness_class") == "FRAGILE"

    current_squad = [
        {"player_id": o.option.player_id, "name": o.option.web_name}
        for o in (ca.options[:3] if ca is not None and ca.options else [])
    ]

    legs = []
    for leg in (auth.get("future_conditional_plan") or [])[:5]:
        gw = _gw_num(leg)
        raw = leg.split(":", 1)[1].strip() if ":" in leg else leg
        raw = raw.split(" - NOT locked in", 1)[0].strip()
        matches_dep = fragile and any(raw in d or d in raw for d in deps)
        legs.append({"gw": gw, "action": raw, "fragile_dependency": bool(matches_dep)})

    return {
        "current_squad": current_squad,
        "now": {"gw": now_gw, "action": now_action or "ROLL"},
        "future_legs": legs,
    }


def build_command_payload(ctx: DashboardContext) -> dict:
    """The COMMAND screen's real, current data - one dominant decision, its
    evidence, its alternative, and what would change it. Every field here
    traces to `ctx.current_rec`/`ctx.ta`/`ctx.ca`/`ctx.freshness`/
    `ctx.cross_check`, already computed once by `build_dashboard_context`."""
    current_rec = ctx.current_rec
    word, cls = _action_word(current_rec, ctx.ta)
    is_stale = bool(ctx.freshness is not None and ctx.freshness.is_stale)
    if is_stale:
        word, cls = "RECOMPUTING", "review"

    auth = (current_rec or {}).get("authoritative")
    diag = (current_rec or {}).get("runner_up_diagnostics") if current_rec else None
    current_gw = _gw_num(ctx.gw_label)

    ev = auth.get("nominal_ev_advantage") if auth else None
    alt_label = (auth.get("best_alternative") or "").partition(": ")[0] if auth else None
    chosen_total = (current_rec or {}).get("path_total") if auth else None
    edge = None
    if auth and ev is not None and alt_label and chosen_total is not None and ev > 0:
        edge = {
            "value": round(ev, 1), "alt_label": alt_label,
            # Real, confirmed bug fix (2026-09-08) - `_horizon_label` returns
            # an HTML-entity-encoded string (`&ndash;`), correct for the HTML
            # renderer it was built for but wrong here: a JSON API must never
            # leak an HTML entity into a field a React client renders as
            # plain text (it would show the literal string "&ndash;", not a
            # dash). Real Unicode en-dash character instead - valid JSON,
            # renders correctly everywhere, same real GW numbers.
            "horizon": _horizon_label(auth, current_gw).replace("&ndash;", "–"),
            "chosen_total": round(chosen_total, 1), "alt_total": round(chosen_total - ev, 1),
        }

    why = []
    if auth:
        robustness = auth.get("robustness_class")
        if robustness == "FRAGILE":
            why.append({"tag": "FRAGILE", "text": "the margin carries this pick, not resilience to bad luck"})
        elif robustness == "ROBUST":
            why.append({"tag": "ROBUST", "text": "holds up even under a real run of bad luck"})
        if auth.get("price_robustness") is False:
            why.append({"tag": None, "text": "a price rise before one of the later moves could force a change of plan"})

    return {
        "gw": {"label": ctx.gw_label, "state": ctx.hero_state_label},
        "status": {
            "recompute_status": ((ctx.live_snapshot_for_strip or {}).get("recommendation") or {}).get("status"),
            "degraded_sources": [
                s["source"] for s in ((ctx.live_snapshot_for_strip or {}).get("source_freshness") or []) if s.get("degraded")
            ],
        },
        "bar": {
            "squad_value_m": round(ctx.squad_value_m, 1),
            "bank_m": round(ctx.bank_m, 1),
            "free_transfers": {"value": ctx.ft_tile_value, "title": ctx.ft_tile_title},
            "actual_points": round(ctx.my_live_score.points, 0) if ctx.my_live_score is not None else None,
            "chips_available": list(ctx.chips_available),
        },
        "action": {"word": word, "class": cls, "is_stale": is_stale},
        "freshness": None if ctx.freshness is None else {
            "computed_at": ctx.freshness.computed_at,
            "decision_id": ctx.freshness.decision_id,
            "model_version": ctx.freshness.model_version,
            "age_relative": getattr(ctx.freshness, "age_relative", None),
            "is_stale": ctx.freshness.is_stale,
            "stale_reason": ctx.freshness.stale_reason,
        },
        "edge": edge,
        "checkpoint_table": _checkpoint_block(
            ctx.sd.get("paths") if ctx.sd else None, (current_rec or {}).get("label"),
            alt_label or None,
        ) if auth else None,
        "contribution": _contribution_block(auth, ctx.ca),
        "trajectory": _trajectory_block(auth, ctx.ca, ctx.gw_label),
        "why": why,
        "captain": _captain_block(ctx.ca),
        "cross_check": None if ctx.cross_check is None else {
            "status": getattr(ctx.cross_check, "status", None),
            "why": getattr(ctx.cross_check, "why", None),
        },
        "alternative": _alternative_block(auth, diag),
        "monitor": _monitor_block(auth),
        "football_context": ctx.football_context,
        "action_squad": ctx.action_squad,
    }
