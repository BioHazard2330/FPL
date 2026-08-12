from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
RAW_DIR = PROJECT_ROOT / "data" / "raw"
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"
DB_PATH = DATA_DIR / "fpl.db"


def _load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"missing config file: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass(frozen=True)
class StorageBudget:
    app_data_target_mb: float
    app_data_max_mb: float
    logs_max_mb: float
    cache_target_mb: float
    cache_max_mb: float
    raw_retention_hours: float


def load_freshness() -> dict:
    return _load_yaml("freshness.yaml")


def load_storage_budget() -> StorageBudget:
    raw = _load_yaml("storage.yaml")
    return StorageBudget(
        app_data_target_mb=raw["app_data"]["target_mb"],
        app_data_max_mb=raw["app_data"]["max_mb"],
        logs_max_mb=raw["logs"]["max_mb"],
        cache_target_mb=raw["cache"]["target_mb"],
        cache_max_mb=raw["cache"]["max_mb"],
        raw_retention_hours=raw["raw_retention_hours"],
    )


def load_sources() -> dict:
    return _load_yaml("sources.yaml")
