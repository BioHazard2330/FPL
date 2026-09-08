"""ADVANCED screen JSON payload (2026-09-08, Phase 8.3/9). v1 scope: System
Health (`monitoring/readiness.py::run_readiness_checks`, `monitoring/
source_status.py::get_source_health`) - real, simple, already-structured
dataclasses, a direct JSON shape with no HTML-parsing work needed.

Real, disclosed deferred scope: Decision Detail, Chip Strategy, Player Odds,
Model-vs-Market Divergence, Optimizer Delta, Independent Model Benchmark,
Regret Analysis, and the raw News/Injuries/Points-Changes feeds
(`legacy.py`'s own many `<details>` disclosures) are real and already
computed, but each needs its own real JSON-shaping pass - comparable-sized
follow-up work, not attempted this pass. The old dashboard's ADVANCED screen
stays the complete real reference until then.

**Real, found-live latency fix (Phase 9)**: `run_readiness_checks` itself
runs a real, full `optimise_squad(conn, n_gw=1)` pass (its own "Squad
optimizer" check) - genuinely expensive (~20s+ against production, confirmed
live via direct isolation timing during this phase's own visual QA sweep),
not something this module's first version accounted for. A small dedicated
TTL cache below (same real "compute once, serve many times" shape `context.
py::get_cached_dashboard_context` already established, deliberately not
merged into that shared cache since readiness/source-health are their own
real, independent concern) - readiness genuinely doesn't change faster than
this either, so a 10-minute-old reading is honest, not stale in any way a
user would notice."""
import threading
import time
from dataclasses import asdict

from fpl_agent.monitoring.dashboard.context import DashboardContext

_CACHE_LOCK = threading.Lock()
_cached_readiness: list | None = None
_cached_sources: list | None = None
_cached_benchmark: dict | None = None
_cached_chips: list | None = None
_cached_at: float = 0.0
_TTL_SECONDS = 600.0


def _build_benchmark_block(conn) -> dict | None:
    """Real Independent Model Benchmark summary (2026-09-08, full redesign
    pass) - the same real `top_divergences`/`latest_solio_snapshot` data
    `benchmark.py::render_benchmark_html` already renders as HTML for the
    old dashboard, reshaped as JSON. `None` when no real Solio snapshot has
    ever been synced (`fpl solio-sync`) - never a fabricated empty list
    dressed up as "no divergences"."""
    from fpl_agent.models.external_benchmark import latest_solio_snapshot, top_divergences

    snapshot = latest_solio_snapshot(conn)
    if snapshot is None:
        return None
    divergences = top_divergences(conn, n=8, min_classification="MATERIAL_DIVERGENCE", snapshot=snapshot)
    return {
        "gameweek": snapshot.gameweek,
        "age_hours": snapshot.age_hours,
        "divergences": [
            {
                "player_id": c.player_id, "web_name": c.web_name, "our_median": c.our_median,
                "solio_pr_points": c.solio_pr_points, "classification": c.classification,
                "largest_driver": c.largest_driver,
            }
            for c in divergences
        ],
    }


def _build_chip_strategy_block(conn, squad_ids: set[int]) -> list[dict]:
    """Real Chip Strategy rows (2026-09-08, full redesign pass) - the same
    real data `legacy.py::_chip_strategy_html` already renders, reshaped as
    JSON. Every value here is a cheap read: `eligible_chips`/`bench_boost_
    value`/`triple_captain_value` are cheap live computations (no ILP
    solve); wildcard/free-hit values and the why-now explanation are read
    from the decision journal (`latest_decision_of_type`), never a live
    re-solve - the same real "expensive strategic recompute happens on its
    own cadence, dashboard reads reuse it" rule this project's chip-value
    display has always followed."""
    from fpl_agent.database.decisions import latest_decision_of_type
    from fpl_agent.optimization.chips import bench_boost_value, eligible_chips, triple_captain_value

    if not squad_ids:
        return []
    squad_list = list(squad_ids)
    windows = eligible_chips(conn)
    if not windows:
        return []

    value_by_type: dict[str, float] = {
        "bboost": bench_boost_value(conn, squad_list), "3xc": triple_captain_value(conn, squad_list),
    }
    age_by_type: dict[str, str] = {}
    logged = latest_decision_of_type(conn, "chip")
    if logged is not None:
        for chip_name, detail_key in (("wildcard", "wildcard_5gw"), ("freehit", "free_hit")):
            if detail_key in logged.detail:
                value_by_type[chip_name] = logged.detail[detail_key]
                age_by_type[chip_name] = logged.created_at

    explanation_by_chip: dict[str, dict] = {}
    season_sim = latest_decision_of_type(conn, "season_sim")
    season_sim_age = season_sim.created_at if season_sim is not None else None
    if season_sim is not None:
        for exp in season_sim.detail.get("chip_explanations") or []:
            existing = explanation_by_chip.get(exp["chip_name"])
            if existing is None or exp["event"] < existing["event"]:
                explanation_by_chip[exp["chip_name"]] = exp

    rows = []
    for w in windows:
        if not w.eligible_now:
            continue
        value = value_by_type.get(w.name)
        exp = explanation_by_chip.get(w.name)
        rows.append({
            "name": w.name, "start_event": w.start_event, "stop_event": w.stop_event,
            "value": value, "value_as_of": age_by_type.get(w.name),
            "best_alternative_event": exp.get("best_alternative_event") if exp else None,
            "best_alternative_value": exp.get("best_alternative_value") if exp else None,
            "opportunity_cost": exp.get("opportunity_cost") if exp else None,
            "confidence": exp.get("confidence") if exp else None,
            "season_sim_as_of": season_sim_age if exp else None,
        })
    return rows


def _get_cached_readiness(conn, squad_ids: set[int] | None = None) -> tuple[list, list, dict | None, list]:
    from fpl_agent.monitoring.readiness import run_readiness_checks
    from fpl_agent.monitoring.source_status import get_source_health

    global _cached_readiness, _cached_sources, _cached_benchmark, _cached_chips, _cached_at
    now = time.monotonic()
    with _CACHE_LOCK:
        if _cached_readiness is not None and (now - _cached_at) < _TTL_SECONDS:
            return _cached_readiness, _cached_sources, _cached_benchmark, _cached_chips
        _cached_readiness = run_readiness_checks(conn)
        _cached_sources = get_source_health(conn)
        try:
            _cached_benchmark = _build_benchmark_block(conn)
        except Exception:
            import logging
            logging.getLogger("fpl_agent.dashboard").exception("benchmark block build failed - omitting this cycle")
            _cached_benchmark = None
        try:
            _cached_chips = _build_chip_strategy_block(conn, squad_ids or set())
        except Exception:
            import logging
            logging.getLogger("fpl_agent.dashboard").exception("chip strategy block build failed - omitting this cycle")
            _cached_chips = []
        _cached_at = time.monotonic()
        return _cached_readiness, _cached_sources, _cached_benchmark, _cached_chips


def run_readiness_refresh_loop(conn_factory, stop_event: threading.Event, interval: float = 480.0) -> None:
    """Same real proactive-background-warm shape as `context.py::run_
    context_refresh_loop` (2026-09-08, Phase 9) - wired into `LiveServer.
    start()` alongside it, so a real user's first ADVANCED-screen visit
    never pays the ~20s+ `optimise_squad` cost live either."""
    while not stop_event.is_set():
        if stop_event.wait(interval):
            break
        conn = conn_factory()
        try:
            from fpl_agent.optimization.locked_squad import get_locked_squad
            locked = get_locked_squad(conn)
            squad_ids = set(locked.squad_ids) if locked is not None else set()
            _get_cached_readiness(conn, squad_ids)
        except Exception:
            import logging
            logging.getLogger("fpl_agent.dashboard").exception(
                "background readiness-cache refresh failed - keeping the previous cached result, next tick will retry"
            )
        finally:
            conn.close()


# Real grouping of `run_readiness_checks`'s own real check names into the
# real pipeline stages this project's architecture actually has (2026-09-08,
# Phase 9 v2 - `FPL_TEMPLATE_LINEAGE.md`'s own disclosed ADVANCED item).
# Never a new computation - every name here is a real check already run;
# this only reorganizes them into the real DATA -> ... -> DECISION order
# `CLAUDE.md`'s own "Critical modules" table already describes.
_PIPELINE_STAGES = [
    ("DATA", ["Database", "Current FPL data", "Rules", "Fixtures", "Prices", "Players"]),
    ("FOOTBALL", ["Injuries", "Team news", "Change detection"]),
    ("PROJECTIONS", ["Player projections"]),
    ("CANDIDATES", ["First-team generation"]),
    ("OPTIMIZER", ["Squad optimizer", "Transfer optimizer", "Captaincy", "Chip engine"]),
]
_STATUS_RANK = {"OK": 0, "DEGRADED": 1, "MISSING": 2}


def _pipeline_block(checks: list, conn) -> list[dict]:
    by_name = {c.name: c for c in checks}
    stages = []
    for label, names in _PIPELINE_STAGES:
        rows = [by_name[n] for n in names if n in by_name]
        if not rows:
            continue
        worst = max(rows, key=lambda c: _STATUS_RANK.get(c.status, 0))
        stages.append({
            "stage": label, "status": worst.status,
            "detail": "; ".join(f"{c.name}: {c.detail}" for c in rows),
        })

    # MARKET - real Solio benchmark sync freshness (never a projection
    # input, purely a comparison layer per CLAUDE.md's own data-source
    # rule - this pipeline row reports whether that comparison data itself
    # is fresh, not whether it changed any real recommendation).
    try:
        from fpl_agent.models.external_benchmark import latest_solio_snapshot
        snap = latest_solio_snapshot(conn)
        if snap is None:
            stages.append({"stage": "MARKET", "status": "MISSING", "detail": "no real Solio snapshot synced yet - run `fpl solio-sync`"})
        else:
            status = "OK" if snap.age_hours < 12 else "DEGRADED"
            stages.append({"stage": "MARKET", "status": status, "detail": f"Solio GW{snap.gameweek} snapshot, {snap.age_hours:.1f}h old"})
    except Exception:
        pass

    return stages


def _robustness_row(ctx: DashboardContext) -> dict | None:
    """Real robustness reading off the SAME `authoritative` decision object
    `command_payload.py` reads for its own WHY-line - never a second
    computation."""
    current_rec = ctx.current_rec
    auth = (current_rec or {}).get("authoritative") if current_rec else None
    if not auth:
        return None
    robustness = auth.get("robustness_class")
    if robustness is None:
        return None
    status = "OK" if robustness == "ROBUST" else "DEGRADED"
    return {"stage": "ROBUSTNESS", "status": status, "detail": f"current decision classified {robustness}"}


def build_advanced_payload(ctx: DashboardContext) -> dict:
    from fpl_agent.database.connection import get_connection

    conn = get_connection()
    try:
        checks, sources, benchmark, chips = _get_cached_readiness(conn, ctx.squad_ids)
        pipeline = _pipeline_block(checks, conn)
    finally:
        conn.close()

    robustness_row = _robustness_row(ctx)
    if robustness_row:
        pipeline.append(robustness_row)

    freshness = ctx.freshness
    pipeline.append({
        "stage": "AUTHORITATIVE DECISION",
        "status": "DEGRADED" if (freshness and freshness.is_stale) else "OK",
        "detail": (
            f"stale - {freshness.stale_reason}" if freshness and freshness.is_stale
            else (f"computed {freshness.age_relative}" if freshness else "no cached decision yet")
        ),
    })

    return {
        "readiness": [asdict(c) for c in checks],
        "sources": [asdict(s) for s in sources],
        "pipeline": pipeline,
        "benchmark": benchmark,
        "chips": chips,
        "freshness": {
            "computed_at": freshness.computed_at if freshness else None,
            "is_stale": freshness.is_stale if freshness else None,
            "stale_reason": freshness.stale_reason if freshness else None,
        } if freshness else None,
    }
