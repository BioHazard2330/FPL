"""Real single-instance process lock (2026-08-29, "final runtime reliability
pass" P0 ask: "two instances of FPLAgentLivePoll/live-match-poll must never
run simultaneously"). Confirmed real production condition this closes: a
long-lived `live-match-poll` process holds its Python imports in memory for
its entire run - restarting the Windows Task Scheduler registration (or a
manual re-launch) can leave the OLD process still alive alongside a NEW one,
both writing the same `data/live_snapshot.json` file with no coordination
("whichever wrote last wins" each cycle - not corrupting, but genuinely
wasteful and a real source of confusing, inconsistent freshness readings).

A plain PID-in-a-file lock, not a DB row or OS-level file lock (`msvcrt`/
`fcntl`) - this needs to survive a hard process kill (Ctrl+C, Task Scheduler
force-stop, a crash) cleanly reclaiming on the NEXT start, which an OS-level
lock already does automatically (released the instant the holding process
dies) but a plain lock FILE does not - so this module does the staleness
check itself: read the PID recorded in the lock file, and only refuse to
acquire when a REAL process is still alive under that exact PID. A crashed
process leaves a lock file with a dead PID - the next start detects that
and reclaims it automatically (real, tested stale-lock recovery), never
requiring a human to manually delete a lock file."""
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fpl_agent.config import DATA_DIR

DEFAULT_LOCK_PATH = DATA_DIR / "live_poll.lock"


def _pid_is_alive(pid: int) -> bool:
    """Real, platform-aware liveness check - the one piece of this module a
    test needs to monkeypatch to simulate a crashed process without actually
    killing anything. POSIX: `os.kill(pid, 0)` raises `ProcessLookupError`
    for a genuinely dead PID (signal 0 sends nothing, only checks
    existence/permission) - `PermissionError` still means "alive, just not
    ours to signal", so that's treated as alive too. Windows: `os.kill` with
    signal 0 doesn't reliably detect a dead PID the same way, so this shells
    out to `tasklist /FI "PID eq N"` (no new dependency) and checks whether
    the PID actually appears in its own output."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired):
            # Real, honest fallback: if we can't even ask the OS, assume
            # alive (the safer failure mode - never steal a lock we can't
            # actually verify is free).
            return True
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass(frozen=True)
class LockResult:
    acquired: bool
    reason: str
    holder_pid: int | None = None


def acquire_singleton_lock(lock_path: Path | None = None, pid_is_alive=None) -> LockResult:
    """Real, atomic-enough acquisition for this project's actual failure
    modes (a stale lock from a crashed process, or a genuine second
    instance) - not hardened against a true OS-level TOCTOU race between two
    processes starting in the exact same instant (this project's own
    real-world trigger is a human/Task-Scheduler restart, not a tight race),
    matching the honest scope this module's own docstring claims.

    `pid_is_alive` is injectable so tests exercise the real staleness-
    recovery LOGIC without needing to spawn/kill real OS processes -
    defaults to `None` and resolves to the MODULE-LEVEL `_pid_is_alive`
    read fresh at call time, same reasoning as `lock_path` below (never
    bound as a Python default-argument value, which would freeze it at
    function-definition time and make it immune to a test's
    `monkeypatch.setattr(process_lock, "_pid_is_alive", ...)` - a real,
    easy-to-miss gotcha this project has hit before with early-bound
    defaults). `lock_path` defaults to the MODULE-LEVEL `DEFAULT_LOCK_PATH`,
    same fresh-lookup reasoning."""
    lock_path = lock_path if lock_path is not None else DEFAULT_LOCK_PATH
    pid_is_alive = pid_is_alive if pid_is_alive is not None else _pid_is_alive
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            existing_pid = int(lock_path.read_text(encoding="utf-8").splitlines()[0].strip())
        except (ValueError, IndexError, OSError):
            existing_pid = None
        if existing_pid is not None and existing_pid != os.getpid() and pid_is_alive(existing_pid):
            return LockResult(acquired=False, reason=f"another live-poll instance is already running (pid {existing_pid})", holder_pid=existing_pid)
        # Either unreadable, or a real dead PID - a genuine stale lock from
        # a crashed/killed prior run. Reclaim it, don't ask a human to
        # delete the file by hand.
    lock_path.write_text(f"{os.getpid()}\n{datetime.now(timezone.utc).isoformat()}\n", encoding="utf-8")
    return LockResult(acquired=True, reason="lock acquired")


def release_singleton_lock(lock_path: Path | None = None) -> None:
    """Only removes the lock file when it's genuinely still ours (real PID
    match) - a process that lost a race/was told the lock was stale and
    then somehow still reaches its own cleanup path must never delete a
    DIFFERENT, legitimately-running instance's live lock."""
    lock_path = lock_path if lock_path is not None else DEFAULT_LOCK_PATH
    if not lock_path.exists():
        return
    try:
        existing_pid = int(lock_path.read_text(encoding="utf-8").splitlines()[0].strip())
    except (ValueError, IndexError, OSError):
        return
    if existing_pid == os.getpid():
        try:
            lock_path.unlink()
        except OSError:
            pass
