"""COMMENTARY - the Premier League's own text commentary for a match (the public Pulselive API behind
premierleague.com: free, no key, an Origin header).

An FPL fixture is matched to the league's fixture id by kickoff time (within an hour) and the two clubs' names; the map is
kept in `app_meta` per FPL fixture. The commentary itself is fetched on request and cached in memory for 30 seconds while
a match is on (an hour once it has finished): it is read live, never stored."""
import logging
import sqlite3
import time
import unicodedata
from datetime import datetime

import requests

_logger = logging.getLogger(__name__)
BASE = "https://footballapi.pulselive.com/football"
HEADERS = {"Origin": "https://www.premierleague.com", "User-Agent": "Mozilla/5.0 (fpl-agent personal research)"}
COMP_SEASON_LABEL = "2026/2027"
_CACHE: dict[int, tuple[float, dict]] = {}
_SEASON: dict[str, int] = {}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    for a, b in (("nott'm", "nottingham"), ("man utd", "manchester united"), ("man city", "manchester city"), ("spurs", "tottenham")):
        s = s.replace(a, b)
    return "".join(ch for ch in s if ch.isalnum() or ch == " ").strip()


def _get(path: str, params: dict | None = None) -> dict:
    r = requests.get(f"{BASE}{path}", params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()


def _season_id() -> int | None:
    if "id" not in _SEASON:
        for c in _get("/competitions/1/compseasons", {"page": 0, "pageSize": 5}).get("content", []):
            if COMP_SEASON_LABEL.split("/")[0] in c.get("label", ""):
                _SEASON["id"] = int(c["id"])
                break
    return _SEASON.get("id")


def pl_fixture_id(conn: sqlite3.Connection, fixture_id: int) -> int | None:
    key = f"pl_fixture_{fixture_id}"
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    if row:
        return int(row["value"])
    f = conn.execute(
        "SELECT f.kickoff_time, th.name AS h, ta.name AS a FROM fixtures f JOIN teams th ON th.id = f.team_h JOIN teams ta ON ta.id = f.team_a "
        "WHERE f.id = ?", (fixture_id,),
    ).fetchone()
    if f is None or not f["kickoff_time"]:
        return None
    season = _season_id()
    if season is None:
        return None
    kick = datetime.fromisoformat(f["kickoff_time"].replace("Z", "+00:00")).timestamp() * 1000
    names = {_norm(f["h"]), _norm(f["a"])}
    for page in range(0, 20):
        data = _get("/fixtures", {"comps": 1, "compSeasons": season, "page": page, "pageSize": 40, "sort": "asc"})
        content = data.get("content", [])
        for c in content:
            millis = (c.get("kickoff") or {}).get("millis") or (c.get("provisionalKickoff") or {}).get("millis")
            if millis is None or abs(millis - kick) > 3_600_000:
                continue
            theirs = {_norm(t["team"].get("name", "")) for t in c.get("teams", [])} | {_norm(t["team"].get("shortName", "")) for t in c.get("teams", [])}
            if all(any(n in x or x in n for x in theirs if x) for n in names):
                pid = int(c["id"])
                conn.execute(
                    "INSERT INTO app_meta (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, str(pid), datetime.utcnow().isoformat()),
                )
                conn.commit()
                return pid
        if page + 1 >= data.get("pageInfo", {}).get("numPages", 0):
            break
    return None


def commentary(conn: sqlite3.Connection, fixture_id: int, limit: int = 250) -> dict:
    now = time.monotonic()
    hit = _CACHE.get(fixture_id)
    if hit and now - hit[0] < (30 if hit[1].get("live") else 3600):
        return hit[1]
    try:
        pid = pl_fixture_id(conn, fixture_id)
        if pid is None:
            return {"status": "unmatched"}
        data = _get(f"/fixtures/{pid}/textstream/EN", {"pageSize": limit, "sort": "desc"})
    except Exception as e:
        _logger.warning("commentary for fixture %s failed: %s", fixture_id, e)
        return {"status": "unavailable"}
    fx = data.get("fixture") or {}
    events = [
        {"type": e.get("type"), "minute": (e.get("time") or {}).get("label"), "text": e.get("text")}
        for e in (data.get("events") or {}).get("content", []) if e.get("text")
    ]
    out = {"status": "ok", "fixture_id": fixture_id, "pl_id": pid, "live": fx.get("phase") not in (None, "F") and fx.get("status") == "L",
           "events": events}
    _CACHE[fixture_id] = (now, out)
    return out
