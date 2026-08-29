"""Real Premier League club crest caching (2026-08-29, forensic product
redesign - direct, angry user correction: "where are the team crests? even
during live tracking i dont see any team crests like fotmob did"). An
earlier session pass confirmed the real official badge CDN
(`resources.premierleague.com/premierleague/badges/{size}/t{code}.png`)
returns a genuine 403 for a BROWSER's cross-origin `<img>` load (it checks
`Referer`) and shipped a text-monogram substitute instead - correct about
the 403, wrong about the fix. Confirmed live this pass: a plain
server-side `requests.get()` (no browser, no Referer header at all)
against the SAME real URL returns a real 200 PNG for every team code
checked. The actual fix is ingestion, not a substitute: fetch each real
crest ONCE here (a real network call, like every other connector in this
project), cache it to disk, and let the dashboard render a same-origin
`<img>` against the cached local file - the browser never makes a
cross-origin request to the CDN at all, so the Referer check it enforces
never applies.

Deliberately NOT called from dashboard rendering code - rendering only
ever reads whatever is already cached (`cached_crest_relpath`, a pure,
fast filesystem check, zero network, safe inside a test suite with no
network access). `sync_team_crests` is the one real, opt-in ingestion
step (`fpl sync-crests`), following this project's own established
"ingestion fetches, rendering reads" split."""
import sqlite3
from pathlib import Path

import requests

from fpl_agent.database import connection as _connection_mod
from fpl_agent.ingestion.sync import update_source_health

_SOURCE_NAME = "pl_badge_cdn"
_CREST_DIR_NAME = "crests"
_CREST_SIZE = 70  # confirmed live: the CDN only serves specific fixed sizes - 80 genuinely 403s, 70 works
_TIMEOUT_SECONDS = 8


def _crest_dir() -> Path:
    # Real test-isolation fix: looked up as a live attribute on the
    # `connection` module (never `from ... import DATA_DIR` at this
    # module's own top level) - the test suite's own `db_conn` fixture
    # monkeypatches `fpl_agent.database.connection.DATA_DIR` specifically
    # (the same pattern `connection.get_connection()` itself relies on for
    # its own `DATA_DIR.mkdir(...)` call) - a plain top-level import here
    # would have captured the real production path once, before any test
    # monkeypatch could apply, and every test would have silently read/
    # written against the real `data/crests/` directory instead of its own
    # isolated tmp one. Confirmed live: this was a real bug, caught by a
    # genuine test failure (a test's own seeded team code collided with a
    # real cached production crest).
    d = _connection_mod.DATA_DIR / _CREST_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def cached_crest_relpath(team_code: int) -> str | None:
    """Pure, fast, network-free - the only function dashboard rendering
    code should ever call. Returns the relative path (for an `<img src=）
    already served same-origin by the local dashboard server) if a real
    crest was already synced for this team code, else `None` (caller falls
    back to the text-monogram badge - never a broken image, never a
    fabricated placeholder)."""
    fpath = _crest_dir() / f"t{team_code}.png"
    if fpath.exists() and fpath.stat().st_size > 0:
        return f"{_CREST_DIR_NAME}/t{team_code}.png"
    return None


def sync_team_crests(conn: sqlite3.Connection, force: bool = False) -> dict:
    """Real, one-time (per team) ingestion step - `fpl sync-crests`. Skips
    a team code already cached unless `force=True` (a real re-fetch is
    only ever needed if a club rebrands its crest, genuinely rare). Uses
    the SAME real `teams.code` field the (now-removed) direct hotlink
    already keyed off - no new crosswalk. Non-fatal per team: one real
    CDN failure never aborts the rest of the real league, and is recorded
    via this project's own standard `source_health` mechanism like every
    other connector."""
    codes = [r["code"] for r in conn.execute("SELECT DISTINCT code FROM teams WHERE code IS NOT NULL").fetchall()]
    fetched, skipped, failed = 0, 0, 0
    for code in codes:
        fpath = _crest_dir() / f"t{code}.png"
        if fpath.exists() and fpath.stat().st_size > 0 and not force:
            skipped += 1
            continue
        try:
            resp = requests.get(
                f"https://resources.premierleague.com/premierleague/badges/{_CREST_SIZE}/t{code}.png",
                timeout=_TIMEOUT_SECONDS,
            )
            if resp.status_code == 200 and resp.content:
                fpath.write_bytes(resp.content)
                fetched += 1
                update_source_health(conn, _SOURCE_NAME, success=True)
            else:
                failed += 1
                update_source_health(conn, _SOURCE_NAME, success=False, error=f"HTTP {resp.status_code}")
        except requests.RequestException as exc:
            failed += 1
            update_source_health(conn, _SOURCE_NAME, success=False, error=str(exc))
    conn.commit()
    return {"fetched": fetched, "skipped": skipped, "failed": failed, "total": len(codes)}
