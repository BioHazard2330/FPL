import logging
from logging.handlers import RotatingFileHandler

from fpl_agent.config import LOGS_DIR

# 5 files x 5MB = 25MB ceiling, matches storage.yaml logs.max_mb
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 4

_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    global _configured
    logger = logging.getLogger("fpl_agent")
    if _configured:
        return logger

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger.setLevel(level)

    file_handler = RotatingFileHandler(
        LOGS_DIR / "fpl_agent.log",
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    _configured = True
    return logger
