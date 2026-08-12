from types import SimpleNamespace

from fpl_agent.scheduler import resources as resources_mod


def _patch_psutil(monkeypatch, *, disk_free_mb, battery_percent, battery_plugged):
    monkeypatch.setattr(resources_mod.psutil, "cpu_percent", lambda interval=0.2: 10.0)
    monkeypatch.setattr(resources_mod.psutil, "cpu_count", lambda: 8)
    monkeypatch.setattr(resources_mod.psutil, "virtual_memory", lambda: SimpleNamespace(percent=50.0))
    monkeypatch.setattr(
        resources_mod.psutil, "disk_usage", lambda path: SimpleNamespace(free=disk_free_mb * 1024 * 1024)
    )
    if battery_percent is None:
        monkeypatch.setattr(resources_mod.psutil, "sensors_battery", lambda: None)
    else:
        monkeypatch.setattr(
            resources_mod.psutil, "sensors_battery",
            lambda: SimpleNamespace(percent=battery_percent, power_plugged=battery_plugged),
        )


def test_healthy_system_does_not_defer(monkeypatch):
    _patch_psutil(monkeypatch, disk_free_mb=5000, battery_percent=100, battery_plugged=True)
    state = resources_mod.check_resources()
    assert state.defer is False
    assert state.defer_reason is None


def test_low_disk_defers(monkeypatch):
    _patch_psutil(monkeypatch, disk_free_mb=500, battery_percent=100, battery_plugged=True)
    state = resources_mod.check_resources()
    assert state.defer is True
    assert "disk" in state.defer_reason


def test_low_unplugged_battery_defers(monkeypatch):
    _patch_psutil(monkeypatch, disk_free_mb=5000, battery_percent=10, battery_plugged=False)
    state = resources_mod.check_resources()
    assert state.defer is True
    assert "battery" in state.defer_reason


def test_low_battery_while_plugged_in_does_not_defer(monkeypatch):
    _patch_psutil(monkeypatch, disk_free_mb=5000, battery_percent=10, battery_plugged=True)
    state = resources_mod.check_resources()
    assert state.defer is False


def test_no_battery_sensor_does_not_defer(monkeypatch):
    _patch_psutil(monkeypatch, disk_free_mb=5000, battery_percent=None, battery_plugged=None)
    state = resources_mod.check_resources()
    assert state.defer is False
    assert state.battery_percent is None
