"""Power gating: what runs, and when (2026-10-13).

Direct user request: the Python processes that ran 24/7 (the sync task every
15 minutes, the FotMob live poll, and above all the dashboard server with four
background cache-refresh threads) used CPU and RAM while gaming. The rule is
now:

- OUTSIDE the active window, nothing stays resident. The first launch of each
  day does one full gather and exits; the rest of the day's launches are
  no-ops that never start Python.
- INSIDE the active window - from `window_lead_hours` before the next FPL
  deadline until `post_deadline_grace_hours` after it - the sync, the live
  poll and the dashboard server run continuously, because team news or an
  injury can land at any moment and is what the deadline decision turns on.

Task Scheduler cannot conditionally fire a trigger, and starting Python
every 15 minutes just to find out it should do nothing costs more than the
thing it saves. So the decision is split: this module computes the window
and writes it to a tiny text file (`data/power_gate.txt`); the VBS launcher
(`scripts/gated_launch.vbs`) reads that file and starts Python only when the
window is open or today's daily run is still owed. `run-scheduled --gated`
re-checks the same rule in Python, so a stale gate file can cost one wasted
launch but never a wrong run.

Failure policy: unknown means run. A missing gate file, a gate whose window
has already passed, or a database with no deadline all fall through to
"allowed", so a broken gate can only cost CPU, never silence the sync.
"""
from __future__ import annotations

import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from fpl_agent import config as _config
from fpl_agent.config import PowerConfig, load_power_config

GATE_FILENAME = "power_gate.txt"
_LAST_OK_KEY = "power_last_ok_epoch"


@dataclass(frozen=True)
class Window:
    active: bool
    start_epoch: int | None
    until_epoch: int | None
    next_deadline_epoch: int | None
    reason: str


def compute_window(
    conn: sqlite3.Connection, now_epoch: float | None = None, cfg: PowerConfig | None = None,
) -> Window:
    """The window around the next deadline whose post-deadline grace has not
    yet run out. `active` is whether `now` is inside it."""
    cfg = cfg or load_power_config()
    now = time.time() if now_epoch is None else now_epoch
    if not cfg.enabled:
        return Window(True, None, None, None, "power gating disabled in config/power.yaml")
    grace = int(cfg.post_deadline_grace_hours * 3600)
    row = conn.execute(
        "SELECT deadline_time_epoch FROM events WHERE deadline_time_epoch IS NOT NULL "
        "AND deadline_time_epoch + ? >= ? ORDER BY deadline_time_epoch LIMIT 1",
        (grace, int(now)),
    ).fetchone()
    if row is None:
        return Window(False, None, None, None, "no upcoming deadline on record")
    deadline = int(row["deadline_time_epoch"])
    start = deadline - int(cfg.window_lead_hours * 3600)
    until = deadline + grace
    active = start <= now <= until
    hours = (deadline - now) / 3600
    reason = (
        f"deadline in {hours:.1f}h - inside the {cfg.window_lead_hours:g}h window" if active and hours >= 0
        else f"{-hours:.1f}h past the deadline - inside the post-deadline grace" if active
        else f"deadline in {hours:.1f}h - window opens in {(start - now) / 3600:.1f}h"
    )
    return Window(active, start, until, deadline, reason)


# ------------------------------------------------------------------ gate file


def gate_path() -> Path:
    return _config.DATA_DIR / GATE_FILENAME


def read_gate(path: Path | None = None) -> dict[str, str]:
    path = path or gate_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out


def _utc_offset_seconds() -> int:
    return -time.altzone if time.localtime().tm_isdst > 0 else -time.timezone


def write_gate(window: Window, daily_done: date | None, path: Path | None = None) -> None:
    """Plain `key=value` lines because the reader is VBScript. `utc_offset`
    lets it turn its local clock into UTC without a WMI call."""
    path = path or gate_path()
    existing = read_gate(path)
    if daily_done is None:
        done = existing.get("daily_done", "")
    else:
        done = daily_done.strftime("%Y%m%d")
    lines = [
        f"from={window.start_epoch or 0}",
        f"until={window.until_epoch or 0}",
        f"next_deadline={window.next_deadline_epoch or 0}",
        f"utc_offset={_utc_offset_seconds()}",
        f"daily_done={done}",
        f"written={int(time.time())}",
        f"reason={window.reason}",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


def gate_says_active(now_epoch: float | None = None, path: Path | None = None) -> bool | None:
    """True/False from the gate file, or None when it cannot say (no file, no
    window recorded, or a window that has already passed and not been
    refreshed). Callers treat None as "carry on as before"."""
    gate = read_gate(path)
    try:
        start, until = int(gate["from"]), int(gate["until"])
    except (KeyError, ValueError):
        return None
    if until <= 0:
        return None
    now = time.time() if now_epoch is None else now_epoch
    if now > until:
        return None
    return start <= now <= until


# --------------------------------------------------------------- run decisions


def record_successful_cycle(conn: sqlite3.Connection, now_epoch: float | None = None) -> None:
    now = int(time.time() if now_epoch is None else now_epoch)
    conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (_LAST_OK_KEY, str(now), datetime.utcnow().isoformat()),
    )
    conn.commit()


def last_successful_cycle(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (_LAST_OK_KEY,)).fetchone()
    try:
        return int(row["value"]) if row else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class RunDecision:
    run: bool
    reason: str
    window: Window


def decide_gated_run(
    conn: sqlite3.Connection,
    cadence_minutes: float,
    *,
    now_epoch: float | None = None,
    fullscreen: bool = False,
    cfg: PowerConfig | None = None,
) -> RunDecision:
    """`run-scheduled --gated`: should this launch do the work?"""
    cfg = cfg or load_power_config()
    now = time.time() if now_epoch is None else now_epoch
    window = compute_window(conn, now, cfg)
    last_ok = last_successful_cycle(conn)

    if window.active:
        if last_ok is not None and now - last_ok < cadence_minutes * 60 * 0.9:
            minutes = (now - last_ok) / 60
            return RunDecision(False, f"in window, last cycle {minutes:.0f}m ago (cadence {cadence_minutes:g}m)", window)
        return RunDecision(True, f"in window ({window.reason})", window)

    if last_ok is not None and date.fromtimestamp(last_ok) == date.fromtimestamp(now):
        return RunDecision(False, "outside window, today's daily run is already done", window)
    hours_since = (now - last_ok) / 3600 if last_ok is not None else None
    if fullscreen and cfg.skip_daily_when_fullscreen and (hours_since is None or hours_since < cfg.force_after_hours):
        return RunDecision(False, "outside window, fullscreen app running - daily run deferred", window)
    return RunDecision(True, "outside window - daily run", window)


def fullscreen_app_running() -> bool:
    """A game (or any fullscreen/presentation app) in the foreground. Windows
    only; anywhere else, or on any error, it says no.

    Direct3D-fullscreen (3) and presentation mode (4) always count. State 2
    ("busy") is what Windows reports for ANY fullscreen window - a borderless
    game, but equally a browser in F11 or a maximised video - so it only
    counts while the machine is actually under load (CPU >= 50% over a
    second); otherwise a fullscreen browser would defer the daily run until
    the 36-hour override."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        state = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
        if state.value in (3, 4):
            return True
        if state.value == 2:
            import psutil

            return psutil.cpu_percent(interval=1.0) >= 50.0
        return False
    except Exception:
        return False


def idle_exit_allowed(now_epoch: float | None = None) -> bool:
    """A server/poller may stop itself when idle only outside the window. When
    the gate cannot say, it may not (the old always-on behaviour)."""
    cfg = load_power_config()
    if not cfg.enabled:
        return False
    return gate_says_active(now_epoch) is False
