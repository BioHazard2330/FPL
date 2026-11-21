import logging
import os
import shutil
from logging.handlers import RotatingFileHandler

from fpl_agent.config import LOGS_DIR

# 5 files x 5MB = 25MB ceiling, matches storage.yaml logs.max_mb
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 4

_configured = False


class SharedRotatingFileHandler(RotatingFileHandler):
    """A rotating log several processes write at once (daemon, live server, live poll, detached jobs). On Windows the
    rename in a normal rollover fails while another process holds the file open (WinError 32), and the stdlib handler
    then drops every line, retrying on each one (found 2026-11-21: nothing logged after 2026-11-20 23:11). When the
    rename is refused, the backups are shifted by copying, the current file is copied to `.1` and emptied in place;
    the other processes keep appending to the same file."""

    def rotate(self, source: str, dest: str) -> None:
        try:
            super().rotate(source, dest)
        except PermissionError:
            shutil.copyfile(source, dest)
            with open(source, "r+b") as f:
                f.truncate(0)

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        if self.backupCount > 0:
            for i in range(self.backupCount - 1, 0, -1):
                sfn = self.rotation_filename(f"{self.baseFilename}.{i}")
                dfn = self.rotation_filename(f"{self.baseFilename}.{i + 1}")
                if os.path.exists(sfn):
                    try:
                        os.replace(sfn, dfn)
                    except PermissionError:
                        shutil.copyfile(sfn, dfn)
            try:
                self.rotate(self.baseFilename, self.rotation_filename(f"{self.baseFilename}.1"))
            except OSError:
                pass
        if not self.delay:
            self.stream = self._open()

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        try:
            if self.stream is not None and os.path.exists(self.baseFilename) and os.path.getsize(self.baseFilename) < self.maxBytes:
                return False
        except OSError:
            return False
        return super().shouldRollover(record)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    global _configured
    logger = logging.getLogger("fpl_agent")
    if _configured:
        return logger

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger.setLevel(level)

    file_handler = SharedRotatingFileHandler(
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
