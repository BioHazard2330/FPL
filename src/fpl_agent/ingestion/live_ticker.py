"""PLAY BY PLAY - FotMob's live ticker for a match: the same file its own site reads (`data.fotmob.com/webcl/ltc/gsm/`,
public, no key, cached 5s at their edge), about 80 lines a match from team news to the full-time report, with goals,
assists, cards, substitutions, VAR and missed penalties tagged with FotMob player ids.

`parse_ticker` turns it into oldest-first rows with a kind, a minute, the running score and the players; `cached_ticker`
keeps the parsed copy in memory (15 seconds while a match can still change, an hour after). Read on request and never
stored. A match the file does not cover falls back to the Premier League's commentary (`ingestion/commentary.py`) in
`monitoring/api/playbyplay_payload.py`.

`match_live` reads one match's live state from FotMob's match details: the score, the clock and the Live Pitch - FotMob's
animated tracker (ball, attack state, Sportradar's feed inside FotMob's own public page), which the app shows by embedding
that page in a frame. The feed behind the page is licensed and is not read or redrawn here; `showSuperLive` is True only
while a covered match is in play.

Assumptions, checked on GW9's ten matches: rows arrive newest first; `Elapsed` 0 is a row with no minute of its own
(pre-match notes, or an analyst's aside during play, which takes the minute before it); `HometeamEvent` on a goal or own
goal is the side the goal counts for (Suzuki's own goal for Villa reads False); on a substitution the first player is
the one coming on."""
import logging
import re
import time

import requests

_logger = logging.getLogger(__name__)
URL = "https://data.fotmob.com/webcl/ltc/gsm/{match_id}_en.json.gz"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_TIMEOUT_SECONDS = 15
LIVE_TTL_SECONDS = 15.0
FINISHED_TTL_SECONDS = 3600.0
_CACHE: dict[str, tuple[float, dict | None]] = {}

KINDS = {
    "G": "goal", "PSG": "goal", "OG": "own_goal", "AS": "assist", "PM": "penalty_missed", "PS": "penalty_saved", "YC": "yellow",
    "Y2C": "red", "RC": "red", "SI": "sub", "var": "var", "injury": "injury", "highlight": "chance",
}
SCORING = {"G", "PSG", "OG"}
SUMMARIES = {"post_match summary": "full_time", "half_time summary": "half_time"}


class TickerUnavailable(Exception):
    pass


def fetch_ticker(match_id: str) -> dict:
    try:
        r = requests.get(URL.format(match_id=match_id), headers=_HEADERS, timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise TickerUnavailable(f"ticker request failed for {match_id}") from exc
    if r.status_code in (403, 404):
        raise TickerUnavailable(f"no ticker file for {match_id}")
    try:
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as exc:
        raise TickerUnavailable(f"bad ticker response for {match_id}") from exc


def _row(e: dict, kind: str, minute: int | None, stoppage: int | None) -> dict:
    home = e.get("HometeamEvent")
    return {
        "id": e.get("MessageId") or str(e.get("OptaEventId")), "kind": kind, "minute": minute, "stoppage": stoppage,
        "side": None if home is None else ("home" if home else "away"), "text": (e.get("Description") or "").strip(),
        "key": bool(e.get("IncludeInHighlight")) or kind != "comment",
        "players": [{"fotmob_id": str(p.get("Id")), "name": p.get("Name")} for p in e.get("Players") or []],
    }


def parse_ticker(payload: dict) -> dict:
    rows: list[dict] = []
    team_news: list[str] = []
    reports: dict[str, str] = {}
    home_goals = away_goals = 0
    last_minute: int | None = None
    last_stoppage: int | None = None
    for e in reversed(payload.get("Events") or []):
        code = e.get("IncidentCode") or "comment"
        text = (e.get("Description") or "").strip()
        if code in SUMMARIES:
            reports[SUMMARIES[code]] = text
            continue
        if code == "team news":
            team_news.append(text)
            continue
        if not text and code not in KINDS:
            continue
        elapsed = e.get("Elapsed") or 0
        plus = e.get("ElapsedPlus") if (e.get("ElapsedPlus") or -1) > 0 else None
        minute, stoppage = (elapsed, plus) if elapsed > 0 else (last_minute, last_stoppage)
        if elapsed > 0:
            last_minute, last_stoppage = elapsed, plus
        row = _row(e, KINDS.get(code, "comment"), minute, stoppage)
        if code in SCORING:
            if e.get("HometeamEvent"):
                home_goals += 1
            else:
                away_goals += 1
            row["score"] = [home_goals, away_goals]
        rows.append(row)
    return {
        "events": rows, "team_news": team_news, "reports": reports, "last_updated": payload.get("LastUpdated"),
        "finished": "full_time" in reports,
    }


def cached_ticker(match_id: str, now: float | None = None, fetch=fetch_ticker) -> dict | None:
    """The parsed ticker, None when FotMob has no file for the match. A failed refresh keeps serving the last good copy."""
    now = time.monotonic() if now is None else now
    hit = _CACHE.get(match_id)
    if hit is not None:
        ttl = FINISHED_TTL_SECONDS if hit[1] is None or hit[1].get("finished") else LIVE_TTL_SECONDS
        if now - hit[0] < ttl:
            return hit[1]
    try:
        parsed = parse_ticker(fetch(match_id))
    except TickerUnavailable as exc:
        _logger.info("live ticker: %s", exc)
        if hit is not None and hit[1] is not None:
            return hit[1]
        parsed = None
    _CACHE[match_id] = (now, parsed)
    return parsed


PITCH_HOST = "https://pub.fotmob.com/"
LIVE_STATE_TTL_SECONDS = 30.0
_LIVE_STATE: dict[str, tuple[float, dict | None]] = {}


def parse_live_state(details: dict) -> dict:
    sl = (details.get("content") or {}).get("superlive") or {}
    url = sl.get("superLiveUrl") or ""
    header = details.get("header") or {}
    teams = header.get("teams") or []
    status = header.get("status") or {}
    return {
        "pitch_url": url if url.startswith(PITCH_HOST) and sl.get("showSuperLive") else None,
        "score": [t.get("score") for t in teams[:2]] if len(teams) >= 2 else None,
        "names": [t.get("name") for t in teams[:2]],
        "minute": re.sub(r"[^0-9+]", "", (status.get("liveTime") or {}).get("short") or "") or None,
        "started": bool(status.get("started")), "finished": bool(status.get("finished")),
    }


def match_live(match_id: str, now: float | None = None, fetch=None) -> dict | None:
    from fpl_agent.ingestion.fotmob_source import FotMobFetchError, fetch_match_details

    now = time.monotonic() if now is None else now
    hit = _LIVE_STATE.get(match_id)
    if hit is not None and now - hit[0] < LIVE_STATE_TTL_SECONDS:
        return hit[1]
    try:
        state = parse_live_state((fetch or fetch_match_details)(match_id))
    except (FotMobFetchError, AttributeError, TypeError, KeyError) as exc:
        _logger.info("live state for %s unavailable: %s", match_id, exc)
        state = hit[1] if hit is not None else None
    _LIVE_STATE[match_id] = (now, state)
    return state
