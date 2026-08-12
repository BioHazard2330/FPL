from dataclasses import dataclass
from pathlib import Path

from fpl_agent.config import CACHE_DIR, DATA_DIR, DB_PATH, LOGS_DIR, load_storage_budget

_TEMP_DIR = DATA_DIR / "tmp"


def _dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def _file_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    return path.stat().st_size / (1024 * 1024)


@dataclass(frozen=True)
class StorageReport:
    db_mb: float
    cache_mb: float
    logs_mb: float
    temp_mb: float
    total_mb: float
    target_mb: float
    max_mb: float
    status: str  # OK, WARN, OVER


def measure_storage() -> StorageReport:
    budget = load_storage_budget()

    db_mb = _file_size_mb(DB_PATH)
    cache_mb = _dir_size_mb(CACHE_DIR)
    logs_mb = _dir_size_mb(LOGS_DIR)
    temp_mb = _dir_size_mb(_TEMP_DIR)
    total = db_mb + cache_mb + logs_mb + temp_mb

    if total > budget.app_data_max_mb:
        status = "OVER"
    elif total > budget.app_data_target_mb:
        status = "WARN"
    else:
        status = "OK"

    return StorageReport(
        db_mb=round(db_mb, 2),
        cache_mb=round(cache_mb, 2),
        logs_mb=round(logs_mb, 2),
        temp_mb=round(temp_mb, 2),
        total_mb=round(total, 2),
        target_mb=budget.app_data_target_mb,
        max_mb=budget.app_data_max_mb,
        status=status,
    )
