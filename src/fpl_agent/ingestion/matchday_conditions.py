"""MATCHDAY CONDITIONS - the ground, the referee and the weather for every Premier League fixture in the next two
gameweeks.

FotMob's match details carry the stadium (name, city, coordinates, capacity) and, once appointed, the referee with his
career figures in the competition (matches, yellow cards a match against the league's, reds, penalties given, fouls a
match). The forecast for the kickoff hour at the stadium's coordinates comes from Open-Meteo (free, no key: temperature,
rain and its chance, wind and gusts, a WMO weather code). Stored per fixture (`fixture_conditions`) and per club's home
ground (`team_venue`, for the map). Context on previews and the map: none of it reaches a projection."""
import logging
import sqlite3
from datetime import date, datetime, timezone

import requests

from fpl_agent.ingestion.fotmob_source import _name_candidates, _strip_punctuation, fetch_match_details, fetch_matches_for_date

_logger = logging.getLogger(__name__)
METEO_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY = "temperature_2m,precipitation,precipitation_probability,wind_speed_10m,wind_gusts_10m,weather_code"
SYNC_HOURS = 3
_META_KEY = "matchday_conditions_synced_at"


def _due(conn: sqlite3.Connection, force: bool) -> bool:
    if force:
        return True
    row = conn.execute("SELECT value FROM app_meta WHERE key=?", (_META_KEY,)).fetchone()
    try:
        last = datetime.fromisoformat(row["value"]) if row and row["value"] else None
    except ValueError:
        last = None
    return last is None or (datetime.now(timezone.utc) - last).total_seconds() >= SYNC_HOURS * 3600


def _find(listing: dict, home: str, away: str) -> str | None:
    hc, ac = _name_candidates(home), _name_candidates(away)
    for league in listing.get("leagues", []):
        for m in league.get("matches", []):
            mh = _strip_punctuation((m.get("home", {}).get("name") or "").lower())
            ma = _strip_punctuation((m.get("away", {}).get("name") or "").lower())
            if any(c in mh or mh in c for c in hc) and any(c in ma or ma in c for c in ac):
                return str(m["id"])
    return None


def parse_conditions(payload: dict) -> dict:
    """Stadium and referee from a FotMob match-details payload."""
    box = ((payload.get("content") or {}).get("matchFacts") or {}).get("infoBox") or {}
    st = box.get("Stadium") or {}
    ref = box.get("Referee") or {}
    stats = {s.get("type"): s for s in ref.get("stats") or []}
    yc = stats.get("yellowCards") or {}
    fouls = stats.get("fouls") or {}
    return {
        "stadium": st.get("name"), "city": st.get("city"), "lat": st.get("lat"), "lon": st.get("long"), "capacity": st.get("capacity"),
        "referee": ref.get("text") or None, "ref_matches": (stats.get("matches") or {}).get("value"),
        "ref_yellows_pm": yc.get("value"), "ref_yellows_avg": yc.get("average"), "ref_reds": (stats.get("redCards") or {}).get("value"),
        "ref_penalties": (stats.get("penalties") or {}).get("value"), "ref_fouls_pm": fouls.get("value"),
    }


def kickoff_forecast(lat: float, lon: float, kickoff: datetime, session=None) -> dict | None:
    """Open-Meteo's hourly forecast for the hour of kickoff at the ground; None beyond its 16-day range or on failure."""
    http = session or requests
    try:
        r = http.get(METEO_URL, params={"latitude": lat, "longitude": lon, "hourly": HOURLY, "timezone": "UTC", "forecast_days": 16}, timeout=20)
        r.raise_for_status()
        h = r.json().get("hourly") or {}
    except Exception as e:
        _logger.warning("open-meteo forecast failed: %s", e)
        return None
    key = kickoff.strftime("%Y-%m-%dT%H:00")
    times = h.get("time") or []
    if key not in times:
        return None
    i = times.index(key)

    def pick(k: str):
        values = h.get(k) or []
        return values[i] if i < len(values) else None

    return {
        "forecast_temp": pick("temperature_2m"), "forecast_precip": pick("precipitation"), "forecast_precip_prob": pick("precipitation_probability"),
        "forecast_wind": pick("wind_speed_10m"), "forecast_gust": pick("wind_gusts_10m"), "forecast_code": pick("weather_code"),
    }


def _store_venue(conn: sqlite3.Connection, team_id: int, cond: dict, at: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO team_venue (team_id, stadium, city, lat, lon, capacity, retrieved_at) VALUES (?,?,?,?,?,?,?)",
        (team_id, cond["stadium"], cond["city"], cond["lat"], cond["lon"], cond["capacity"], at),
    )


def sync_conditions(conn: sqlite3.Connection, force: bool = False, details=None, listing=None, forecast=None) -> dict:
    if not _due(conn, force):
        return {"status": "fresh"}
    details = details or fetch_match_details
    listing = listing or fetch_matches_for_date
    forecast = forecast or kickoff_forecast
    now = datetime.now(timezone.utc)
    nxt = conn.execute(
        "SELECT MIN(event) AS e FROM fixtures WHERE finished = 0 AND event IS NOT NULL AND kickoff_time > ?", (now.isoformat(),),
    ).fetchone()["e"]
    if nxt is None:
        return {"status": "no_fixtures"}
    rows = conn.execute(
        "SELECT f.id, f.kickoff_time, f.team_h, th.name AS home, ta.name AS away, c.fotmob_match_id AS known FROM fixtures f "
        "JOIN teams th ON th.id = f.team_h JOIN teams ta ON ta.id = f.team_a LEFT JOIN fixture_conditions c ON c.fixture_id = f.id "
        "WHERE f.event IN (?, ?) AND f.finished = 0 AND f.kickoff_time IS NOT NULL", (nxt, nxt + 1),
    ).fetchall()
    listings: dict[date, dict] = {}
    at = now.isoformat()
    done = failed = 0
    for r in rows:
        kick = datetime.fromisoformat(r["kickoff_time"].replace("Z", "+00:00"))
        mid = r["known"]
        try:
            if mid is None:
                day = kick.date()
                if day not in listings:
                    listings[day] = listing(day)
                mid = _find(listings[day], r["home"], r["away"])
            if mid is None:
                continue
            cond = parse_conditions(details(mid))
        except Exception as e:
            _logger.warning("conditions for fixture %s failed: %s", r["id"], e)
            failed += 1
            continue
        wx = forecast(cond["lat"], cond["lon"], kick) if cond.get("lat") is not None else None
        cols = {**cond, **(wx or {}), "fotmob_match_id": mid, "forecast_at": at if wx else None, "retrieved_at": at}
        conn.execute(
            f"INSERT INTO fixture_conditions (fixture_id, {', '.join(cols)}) VALUES (?, {', '.join('?' * len(cols))}) "
            "ON CONFLICT(fixture_id) DO UPDATE SET " + ", ".join(f"{k}=COALESCE(excluded.{k}, fixture_conditions.{k})" for k in cols),
            (r["id"], *cols.values()),
        )
        if cond.get("lat") is not None:
            _store_venue(conn, r["team_h"], cond, at)
        done += 1
    for t in conn.execute("SELECT id FROM teams WHERE id NOT IN (SELECT team_id FROM team_venue)").fetchall():
        m = conn.execute(
            "SELECT fotmob_match_id FROM match_intelligence WHERE home_team_id = ? ORDER BY kickoff_utc DESC LIMIT 1", (t["id"],),
        ).fetchone()
        if not m:
            continue
        try:
            cond = parse_conditions(details(m["fotmob_match_id"]))
        except Exception:
            continue
        if cond.get("lat") is not None:
            _store_venue(conn, t["id"], cond, at)
    conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (_META_KEY, at, at),
    )
    conn.commit()
    return {"status": "ok", "fixtures": done, "failed": failed}


def conditions_by_fixture(conn: sqlite3.Connection, fixture_ids: list[int]) -> dict[int, dict]:
    if not fixture_ids:
        return {}
    return {r["fixture_id"]: dict(r) for r in conn.execute(
        f"SELECT * FROM fixture_conditions WHERE fixture_id IN ({','.join('?' * len(fixture_ids))})", fixture_ids)}
