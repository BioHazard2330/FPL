"""
Resource-aware scheduling (section 21-22). Checked before any scheduled sync so
the app never burns CPU/battery/network when the machine can't spare it.
"""

from dataclasses import dataclass

import psutil

from fpl_agent.config import PROJECT_ROOT

_MIN_FREE_DISK_MB = 1024
_MIN_BATTERY_PERCENT = 15


@dataclass(frozen=True)
class ResourceState:
    cpu_count: int
    cpu_percent: float
    ram_percent: float
    free_disk_mb: float
    battery_percent: float | None
    battery_plugged: bool | None
    defer: bool
    defer_reason: str | None


def check_resources() -> ResourceState:
    cpu_percent = psutil.cpu_percent(interval=0.2)
    ram_percent = psutil.virtual_memory().percent
    free_disk_mb = psutil.disk_usage(str(PROJECT_ROOT)).free / (1024 * 1024)

    battery = psutil.sensors_battery()
    battery_percent = battery.percent if battery else None
    battery_plugged = battery.power_plugged if battery else None

    defer_reason = None
    if free_disk_mb < _MIN_FREE_DISK_MB:
        defer_reason = f"low disk: {free_disk_mb:.0f}MB free"
    elif battery is not None and not battery.power_plugged and battery.percent < _MIN_BATTERY_PERCENT:
        defer_reason = f"low battery: {battery.percent:.0f}% and not charging"

    return ResourceState(
        cpu_count=psutil.cpu_count() or 1,
        cpu_percent=cpu_percent,
        ram_percent=ram_percent,
        free_disk_mb=round(free_disk_mb, 1),
        battery_percent=battery_percent,
        battery_plugged=battery_plugged,
        defer=defer_reason is not None,
        defer_reason=defer_reason,
    )
