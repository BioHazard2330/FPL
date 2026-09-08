"""Real regression coverage for the DashboardContext cache (2026-09-08,
Phase 8.2 Stage 2) - found live: `build_dashboard_context` takes ~60s
against the real production DB (`_analyze_locked_decisions` + `generate_
build_team_report` dominate), so the JSON API layer must share ONE cached
context across requests within a TTL window, never rebuild per request."""
import threading
import time

from fpl_agent.monitoring.dashboard import context as context_mod
from fpl_agent.monitoring.dashboard.context import get_cached_dashboard_context, run_context_refresh_loop
from test_optimization_squad import _seed


def test_cached_context_is_reused_within_the_ttl(db_conn, monkeypatch):
    calls = []
    real_build = context_mod.build_dashboard_context

    def counting_build(conn, **kwargs):
        calls.append(1)
        return real_build(conn, **kwargs)

    monkeypatch.setattr(context_mod, "build_dashboard_context", counting_build)
    monkeypatch.setattr(context_mod, "_cached_context", None)
    monkeypatch.setattr(context_mod, "_cached_at", 0.0)
    _seed(db_conn, budget_tenths=950, club_limit=4)

    first = get_cached_dashboard_context(db_conn, ttl_seconds=60.0)
    second = get_cached_dashboard_context(db_conn, ttl_seconds=60.0)

    assert first is second
    assert len(calls) == 1


def test_cached_context_rebuilds_after_the_ttl_expires(db_conn, monkeypatch):
    calls = []
    real_build = context_mod.build_dashboard_context

    def counting_build(conn, **kwargs):
        calls.append(1)
        return real_build(conn, **kwargs)

    monkeypatch.setattr(context_mod, "build_dashboard_context", counting_build)
    monkeypatch.setattr(context_mod, "_cached_context", None)
    monkeypatch.setattr(context_mod, "_cached_at", 0.0)
    _seed(db_conn, budget_tenths=950, club_limit=4)

    get_cached_dashboard_context(db_conn, ttl_seconds=0.05)
    time.sleep(0.1)
    get_cached_dashboard_context(db_conn, ttl_seconds=0.05)

    assert len(calls) == 2


def test_refresh_loop_proactively_rebuilds_before_a_request_ever_needs_to(db_conn, monkeypatch):
    """Real Phase 9 latency fix - `run_context_refresh_loop` must rebuild the
    shared cache on its own timer, so a real `/api/*` request never has to
    pay the rebuild cost itself under normal operation (only a fresh boot,
    or the refresh loop having genuinely never run yet, hits the lazy
    on-demand path in `get_cached_dashboard_context`)."""
    calls = []
    real_build = context_mod.build_dashboard_context

    def counting_build(conn, **kwargs):
        calls.append(1)
        return real_build(conn, **kwargs)

    monkeypatch.setattr(context_mod, "build_dashboard_context", counting_build)
    monkeypatch.setattr(context_mod, "_cached_context", None)
    monkeypatch.setattr(context_mod, "_cached_at", 0.0)
    _seed(db_conn, budget_tenths=950, club_limit=4)

    from fpl_agent.database.connection import get_connection

    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_context_refresh_loop, args=(get_connection, stop_event), kwargs={"interval": 0.05}, daemon=True,
    )
    thread.start()
    time.sleep(0.6)
    stop_event.set()
    thread.join(timeout=2)

    # The loop waits `interval` before its first rebuild (never rebuilds on
    # the same tick it starts) - real, multiple background rebuilds landed
    # in this window with zero request ever calling `get_cached_dashboard_
    # context` itself.
    assert len(calls) >= 2
    # A request arriving now finds an already-warm cache - no new build.
    before = len(calls)
    get_cached_dashboard_context(db_conn, ttl_seconds=600.0)
    assert len(calls) == before
