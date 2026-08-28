"""Real single-instance lock guard for `fpl run-scheduled` (2026-08-28,
direct user audit: "verify the process-lock fix against BOTH
FPLAgentLivePoll and FPLAgentSync" - `live-match-poll` already had this,
`run-scheduled` didn't). Only tests the NEW guard itself (a second instance
must exit cleanly before touching any real work) - `run_scheduled`'s own
happy path already has full network/DB mocking cost that isn't worth
duplicating here; the lock is a pure short-circuit at the top of the
function, verifiable in isolation."""
from click.testing import CliRunner

import fpl_agent.cli.main as main_mod
import fpl_agent.scheduler.process_lock as process_lock_mod
from fpl_agent.cli.main import cli
from fpl_agent.scheduler.resources import ResourceState


def test_run_scheduled_exits_cleanly_when_a_real_lock_is_already_held(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)

    def _boom(*a, **k):
        raise AssertionError("run_sync must never be called when the lock guard should short-circuit first")

    monkeypatch.setattr(main_mod, "run_sync", _boom)
    monkeypatch.setattr(process_lock_mod, "_pid_is_alive", lambda pid: True)
    (tmp_path / "run_scheduled.lock").write_text("999999\n2026-08-28T00:00:00+00:00\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["run-scheduled"])

    assert result.exit_code == 0, result.output
    assert "already running" in result.output


def test_run_scheduled_lock_file_is_released_after_a_deferred_run(db_conn, tmp_path, monkeypatch):
    """The lock must not wedge - a real early exit (resources constrained)
    still releases it, so the NEXT tick can acquire cleanly."""
    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        main_mod, "check_resources",
        lambda: ResourceState(
            cpu_count=1, cpu_percent=0.0, ram_percent=0.0, free_disk_mb=1.0,
            battery_percent=None, battery_plugged=None, defer=True, defer_reason="test defer",
        ),
    )

    result = CliRunner().invoke(cli, ["run-scheduled"])

    assert result.exit_code == 0, result.output
    assert "deferred" in result.output
    assert not (tmp_path / "run_scheduled.lock").exists()
