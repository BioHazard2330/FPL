import os

from fpl_agent.scheduler.process_lock import acquire_singleton_lock, release_singleton_lock


def test_acquire_succeeds_when_no_lock_file_exists(tmp_path):
    lock_path = tmp_path / "live_poll.lock"
    result = acquire_singleton_lock(lock_path)
    assert result.acquired is True
    assert lock_path.exists()
    assert lock_path.read_text().splitlines()[0] == str(os.getpid())


def test_acquire_fails_when_a_real_live_process_holds_the_lock(tmp_path):
    lock_path = tmp_path / "live_poll.lock"
    lock_path.write_text("99999\n2026-08-29T10:00:00+00:00\n", encoding="utf-8")

    result = acquire_singleton_lock(lock_path, pid_is_alive=lambda pid: True)

    assert result.acquired is False
    assert result.holder_pid == 99999
    assert "already running" in result.reason
    # Must never overwrite a real held lock.
    assert lock_path.read_text().splitlines()[0] == "99999"


def test_stale_lock_from_a_crashed_process_is_reclaimed(tmp_path):
    """Direct P0 acceptance test: "test stale-lock recovery after process
    crash/restart" - a lock file left behind by a real dead PID must be
    reclaimed automatically, never require a human to delete it by hand."""
    lock_path = tmp_path / "live_poll.lock"
    lock_path.write_text("12345\n2026-08-29T09:00:00+00:00\n", encoding="utf-8")

    result = acquire_singleton_lock(lock_path, pid_is_alive=lambda pid: False)

    assert result.acquired is True
    assert lock_path.read_text().splitlines()[0] == str(os.getpid())


def test_acquire_reclaims_an_unreadable_lock_file(tmp_path):
    lock_path = tmp_path / "live_poll.lock"
    lock_path.write_text("garbage, not a pid", encoding="utf-8")

    result = acquire_singleton_lock(lock_path, pid_is_alive=lambda pid: True)

    assert result.acquired is True


def test_release_removes_a_lock_this_process_owns(tmp_path):
    lock_path = tmp_path / "live_poll.lock"
    acquire_singleton_lock(lock_path)

    release_singleton_lock(lock_path)

    assert not lock_path.exists()


def test_release_never_removes_a_lock_owned_by_a_different_pid(tmp_path):
    """A process that lost the acquisition race must never delete the
    winner's real, live lock file on its own way out."""
    lock_path = tmp_path / "live_poll.lock"
    lock_path.write_text("54321\n2026-08-29T09:00:00+00:00\n", encoding="utf-8")

    release_singleton_lock(lock_path)

    assert lock_path.exists()
    assert lock_path.read_text().splitlines()[0] == "54321"


def test_release_is_a_safe_no_op_when_no_lock_file_exists(tmp_path):
    release_singleton_lock(tmp_path / "does_not_exist.lock")
