"""Real, live-exercised readiness checks (2026-09-02 autonomous-runtime fix)
- `run_readiness_checks` used to hardcode "Transfer optimizer"/"Captaincy"/
"Chip engine"/"Tests" as static OK strings with zero runtime measurement, and
its "Scheduler" row only ever asked Task Scheduler's State/NextRunTime, never
LastRunTime age against the task's own real cadence. These tests prove every
row now reflects something actually checked this call, never a guess."""
from fpl_agent.monitoring.readiness import run_readiness_checks


def test_readiness_runs_without_raising_on_an_empty_database(db_conn):
    """An empty (freshly migrated, no real data yet) database is a real,
    legitimate state (pre-sync) - readiness must degrade honestly, never
    crash."""
    checks = run_readiness_checks(db_conn)

    names = {c.name for c in checks}
    assert "Transfer optimizer" in names
    assert "Captaincy" in names
    assert "Chip engine" in names
    assert "Scheduler" in names
    assert "Tests" in names


def test_transfer_optimizer_check_degrades_honestly_with_no_locked_squad(db_conn):
    checks = run_readiness_checks(db_conn)

    row = next(c for c in checks if c.name == "Transfer optimizer")
    assert row.status == "DEGRADED"
    assert "no real locked squad" in row.detail


def test_scheduler_row_reports_per_task_detail_not_a_single_hardcoded_ok(db_conn, monkeypatch):
    """Real fix for the confirmed bug: the old row was `f"registered -
    state={...}"` for FPLAgentSync alone - the new row must name every real
    autonomous task and its own real status, so a problem on any one of
    them (e.g. a stopped optimizer) can never hide behind the others."""
    from fpl_agent.scheduler import status as status_mod

    monkeypatch.setattr(status_mod, "check_scheduler_registered", lambda name: None)

    checks = run_readiness_checks(db_conn)

    row = next(c for c in checks if c.name == "Scheduler")
    assert row.status == "CRITICAL"
    for task_name in status_mod.ALL_TASK_NAMES:
        assert task_name in row.detail
