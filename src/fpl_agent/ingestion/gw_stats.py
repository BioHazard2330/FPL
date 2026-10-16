"""Per-gameweek player stats from the official live endpoint.

`event/{n}/live` is one request for the whole league's gameweek and carries the
expected-stat columns (xG, xA, xGC) next to the points they turned into, which is
exactly what a luck audit needs. Finished gameweeks are fetched once and kept;
the latest finished gameweek is re-fetched on every run because bonus points and
corrections land after the last whistle. Free, keyless, one request per
gameweek."""
import logging
from datetime import datetime, timezone

import requests

from fpl_agent.ingestion.sync import update_source_health
from fpl_agent.models.rules import current_season

_logger = logging.getLogger("fpl_agent.gw_stats")
_LIVE_URL = "https://fantasy.premierleague.com/api/event/{event}/live/"
_TIMEOUT_SECONDS = 30
_SOURCE = "fpl_api_event_live_stats"


class GwStatsFetchError(Exception):
    pass


def fetch_event_live(event: int) -> dict:
    try:
        resp = requests.get(_LIVE_URL.format(event=event), timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise GwStatsFetchError(f"failed to fetch event {event} live stats: {exc}") from exc


def _f(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def store_event(conn, event: int, season: str, payload: dict, now: str) -> int:
    rows = 0
    for el in payload.get("elements", []):
        s = el.get("stats") or {}
        if not s.get("minutes") and not s.get("total_points"):
            continue
        fixtures = len(el.get("explain") or []) or 1
        conn.execute(
            "INSERT INTO player_gw_stats (player_id, event, season, minutes, starts, goals, assists, clean_sheets, goals_conceded, "
            "own_goals, penalties_missed, penalties_saved, yellow_cards, red_cards, saves, bonus, bps, defensive_contribution, "
            "xg, xa, xgc, total_points, fixtures, retrieved_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(player_id, event, season) DO UPDATE SET minutes=excluded.minutes, starts=excluded.starts, goals=excluded.goals, "
            "assists=excluded.assists, clean_sheets=excluded.clean_sheets, goals_conceded=excluded.goals_conceded, "
            "own_goals=excluded.own_goals, penalties_missed=excluded.penalties_missed, penalties_saved=excluded.penalties_saved, "
            "yellow_cards=excluded.yellow_cards, red_cards=excluded.red_cards, saves=excluded.saves, bonus=excluded.bonus, bps=excluded.bps, "
            "defensive_contribution=excluded.defensive_contribution, xg=excluded.xg, xa=excluded.xa, xgc=excluded.xgc, "
            "total_points=excluded.total_points, fixtures=excluded.fixtures, retrieved_at=excluded.retrieved_at",
            (
                el["id"], event, season, s.get("minutes", 0), s.get("starts"), s.get("goals_scored", 0), s.get("assists", 0),
                s.get("clean_sheets", 0), s.get("goals_conceded", 0), s.get("own_goals", 0), s.get("penalties_missed", 0),
                s.get("penalties_saved", 0), s.get("yellow_cards", 0), s.get("red_cards", 0), s.get("saves", 0), s.get("bonus", 0),
                s.get("bps"), s.get("defensive_contribution"), _f(s.get("expected_goals")), _f(s.get("expected_assists")),
                _f(s.get("expected_goals_conceded")), s.get("total_points", 0), fixtures, now,
            ),
        )
        rows += 1
    return rows


def sync_gw_stats(conn) -> dict:
    """Fetch every finished gameweek not yet stored, plus the latest finished one
    again. Returns the events touched; a failed fetch is recorded against source
    health and does not stop the others."""
    season = current_season(conn)
    finished = [r["id"] for r in conn.execute("SELECT id FROM events WHERE finished = 1 ORDER BY id")]
    if not finished:
        return {"events": [], "rows": 0}
    have = {r["event"] for r in conn.execute("SELECT DISTINCT event FROM player_gw_stats WHERE season=?", (season,))}
    todo = sorted({e for e in finished if e not in have} | {finished[-1]})
    now = datetime.now(timezone.utc).isoformat()
    total = 0
    done = []
    for event in todo:
        try:
            payload = fetch_event_live(event)
            total += store_event(conn, event, season, payload, now)
            conn.commit()
            update_source_health(conn, _SOURCE, success=True, error=None)
            done.append(event)
        except GwStatsFetchError as exc:
            conn.rollback()
            update_source_health(conn, _SOURCE, success=False, error=str(exc))
            _logger.warning("gw stats: %s", exc)
    return {"events": done, "rows": total}
