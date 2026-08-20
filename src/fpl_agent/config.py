import os
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


def load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def get_odds_api_key() -> str | None:
    return os.environ.get("ODDS_API_KEY")


def get_telegram_config() -> tuple[str, str] | None:
    """Both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set - a bot token
    alone can't send to anyone. Free (Telegram's Bot API has no cost)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    return (token, chat_id) if token and chat_id else None


def get_discord_webhook_url() -> str | None:
    """Free (Discord webhooks have no cost)."""
    return os.environ.get("DISCORD_WEBHOOK_URL")


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
    news_retention_days: float


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
        news_retention_days=raw["news_retention_days"],
    )


def load_sources() -> dict:
    return _load_yaml("sources.yaml")
