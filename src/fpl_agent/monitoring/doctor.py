import shutil
from dataclasses import dataclass

from fpl_agent.config import PROJECT_ROOT, load_freshness, load_sources, load_storage_budget
from fpl_agent.database.connection import get_connection
from fpl_agent.database.migrate import pending_migrations

_MIN_FREE_DISK_MB = 1024  # 1GB floor before flagging low disk


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def _check_database() -> CheckResult:
    try:
        conn = get_connection()
        conn.execute("SELECT 1")
        conn.close()
        return CheckResult("database", True, "reachable")
    except Exception as e:
        return CheckResult("database", False, str(e))


def _check_migrations() -> CheckResult:
    try:
        conn = get_connection()
        pending = pending_migrations(conn)
        conn.close()
        if pending:
            return CheckResult("migrations", False, f"pending: {', '.join(pending)}")
        return CheckResult("migrations", True, "up to date")
    except Exception as e:
        return CheckResult("migrations", False, str(e))


def _check_disk() -> CheckResult:
    usage = shutil.disk_usage(PROJECT_ROOT)
    free_mb = usage.free / (1024 * 1024)
    if free_mb < _MIN_FREE_DISK_MB:
        return CheckResult("disk", False, f"{free_mb:.0f}MB free, below {_MIN_FREE_DISK_MB}MB floor")
    return CheckResult("disk", True, f"{free_mb / 1024:.1f}GB free")


def _check_config() -> CheckResult:
    try:
        load_freshness()
        load_storage_budget()
        load_sources()
        return CheckResult("config", True, "valid")
    except Exception as e:
        return CheckResult("config", False, str(e))


def run_checks() -> list[CheckResult]:
    return [
        _check_database(),
        _check_migrations(),
        _check_disk(),
        _check_config(),
    ]
