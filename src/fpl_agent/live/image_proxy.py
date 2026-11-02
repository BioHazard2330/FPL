"""SAME-ORIGIN IMAGES - Premier League headshots and FPL shirts served through the dashboard (`/img?u=<url>`), so pages
can draw them onto a canvas (poster export, trading cards) without the browser refusing a cross-origin image. Only the
two official hosts are allowed; each image is cached on disk (`data/cache/img`, oldest dropped past `MAX_FILES`)."""
import hashlib
from pathlib import Path
from urllib.parse import urlparse

import requests

ALLOWED_HOSTS = {"resources.premierleague.com", "fantasy.premierleague.com"}
MAX_FILES = 1500
_TYPES = {".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}


def fetch_image(url: str, cache_dir: Path) -> tuple[bytes, str] | None:
    """(bytes, content type) for an allowed image URL, from the disk cache or the network; None if refused or missing."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        return None
    suffix = Path(parsed.path).suffix.lower()
    ctype = _TYPES.get(suffix)
    if ctype is None:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / (hashlib.sha1(url.encode()).hexdigest() + suffix)
    if path.exists():
        return path.read_bytes(), ctype
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (fpl-agent personal dashboard)"})
    except requests.RequestException:
        return None
    if r.status_code != 200 or not r.content:
        return None
    path.write_bytes(r.content)
    files = sorted(cache_dir.iterdir(), key=lambda p: p.stat().st_mtime)
    for old in files[:-MAX_FILES]:
        old.unlink(missing_ok=True)
    return r.content, ctype
