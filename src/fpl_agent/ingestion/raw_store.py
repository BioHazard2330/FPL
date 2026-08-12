import json
import time
from datetime import datetime, timezone
from pathlib import Path

from fpl_agent.config import RAW_DIR


def save_raw(source_name: str, data) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RAW_DIR / f"{source_name}_{stamp}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def prune_raw(retention_hours: float) -> int:
    if not RAW_DIR.exists():
        return 0
    cutoff = time.time() - retention_hours * 3600
    deleted = 0
    for path in RAW_DIR.glob("*.json"):
        if path.stat().st_mtime < cutoff:
            path.unlink()
            deleted += 1
    return deleted
