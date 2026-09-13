"""Real team-level match odds via API-Football (api-sports.io) - replaces
the-odds-api.com-based `odds_live_source.py` (removed 2026-09-13).

Direct user report: "ran out of monthly credits... just remove it and find
a better source." Real root cause found before removing anything: the-odds-
api.com's free tier is 500 CREDITS PER MONTH, not the 500-requests-PER-DAY
this project's own removed module assumed in its docstring - and that
module never throttled itself at all, calling the API on every single
`run_scheduled` tick (which CLAUDE.md documents as adaptive down to ~15min
near a deadline). That alone could burn a whole month's budget in days -
a real, disclosed bug, not evidence the free tier itself was too small.

Real web research (2026-09-13) into free alternatives before building this:
- SportsGameOdds' free "Amateur" tier explicitly excludes EPL (its own
  pricing page lists only NFL/NBA/MLB/NHL/CFB/CBB/UCL/MLS on that tier).
- odds-api.io's free tier has new signups "paused indefinitely" (its own
  pricing page) - a new key can't currently be obtained at all.
- Betfair Exchange's real-time (non-delayed) API access carries a real
  GBP 299 one-off activation fee - violates this project's free-resources-
  only rule; the free "delayed" key is real but too stale to blend live.
API-Football is the one real, currently-signup-able, confirmed-free option:
100 requests/day (a flat request count, not a variable-cost credit), every
endpoint including /odds available on the free plan (its own docs,
corroborated by independent secondary sources), EPL a top-tier covered
league, real odds available 1-14 days before kickoff.

Real, disclosed gap: no free anytime-goalscorer PLAYER PROP source was
found in that same research pass (API-Football's own odds coverage is
team-market only: match winner/totals/BTTS/handicap/corners/cards - no
individual player markets). `ingestion/player_odds_source.py` and its
the-odds-api.com-specific fetch code were removed rather than pointed at a
dead vendor. `models/expected_points.py::_market_blended_share` (the code
that BLENDS a player-odds row into the projection) is untouched and still
fully functional - it degrades to the unchanged model share whenever no
`player_odds_live` row exists, exactly as designed; it simply has no live
data to blend until a real free player-prop source turns up. The reusable
two-outcome devig math that source used (`devig_anytime_scorer_probability`)
was folded into `models/odds_devig.py::devig_two_outcome_prop` rather than
deleted, ready for whatever connector eventually feeds that table again.

This module learns directly from the root-cause bug above: a real,
app_meta-backed freshness gate (same pattern `solio_source.py::should_sync`
already uses) throttles the WHOLE sync globally rather than per-fixture,
and one call covers a whole matchday date's fixtures at once (never one
call per fixture) - see `config/freshness.yaml`'s `api_football_odds` key
for the real budget math behind the chosen cadence.

Needs one real live-verification run before being trusted, per this
project's own standing rule for a new external connector (CLAUDE.md's
data-source rules: "mocked payloads pass while the real integration
silently no-ops"). The response shape below (`bookmakers[].bets[].values[]`,
bet names "Match Winner"/"Goals Over/Under") is built from API-Football's
own publicly documented schema, but their docs site itself blocked
automated fetches (Cloudflare) while this was written, so it has NOT yet
been checked against one real live payload. Parsing is defensive throughout
(never crashes on an unexpected shape, same non-fatal-per-item posture
every other connector here already uses) - a real shape mismatch degrades
to zero matched fixtures, visible via `fpl doctor`/`fpl source-status`,
never a crash and never a silent fabrication.
"""
from datetime import datetime, timedelta, timezone

import requests

from fpl_agent.config import get_api_football_key, load_freshness
from fpl_agent.ingestion.market_identity import match_fixture_by_teams_and_kickoff
from fpl_agent.ingestion.sync import update_source_health

_ODDS_URL = "https://v3.football.api-sports.io/odds"
_TIMEOUT_SECONDS = 15
_SOURCE_NAME = "api_football"
_EPL_LEAGUE_ID = 39  # API-Football's own well-known, stable id for the English Premier League
_HORIZON_DAYS = 14  # API-Football's own documented odds-availability window


class ApiFootballOddsFetchError(Exception):
    pass


def _safe_error(exc: requests.RequestException, context: str) -> str:
    # Same real secret-in-error-message guard the removed odds_live_source.py
    # used - the key here travels as a header, not a URL param, so it's a
    # smaller real leak surface, but requests' own HTTPError/ConnectionError
    # __str__() can still echo request internals - stick to known-safe fields.
    response = getattr(exc, "response", None)
    if response is not None:
        return f"{context}: api-football.com returned HTTP {response.status_code}"
    return f"{context}: request failed (see network logs)"


def fetch_odds_for_date(date: str, season_start_year: int) -> list[dict]:
    api_key = get_api_football_key()
    if not api_key:
        raise ApiFootballOddsFetchError(
            "API_FOOTBALL_KEY not set - see .env.example for how to configure a free api-football.com key"
        )
    try:
        resp = requests.get(
            _ODDS_URL,
            params={"league": _EPL_LEAGUE_ID, "season": season_start_year, "date": date},
            headers={"x-apisports-key": api_key},
            timeout=_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ApiFootballOddsFetchError(_safe_error(exc, "failed to fetch match odds")) from exc
    payload = resp.json()
    return payload.get("response", []) if isinstance(payload, dict) else []


def _find_bet(bookmaker: dict, name: str) -> dict | None:
    for bet in bookmaker.get("bets", []) or []:
        if bet.get("name") == name:
            return bet
    return None


def _parse_bookmaker(bookmaker: dict) -> dict | None:
    match_winner = _find_bet(bookmaker, "Match Winner")
    if match_winner is None:
        return None
    values = {v.get("value"): v.get("odd") for v in match_winner.get("values", []) or []}
    if not all(k in values and values[k] for k in ("Home", "Draw", "Away")):
        return None
    try:
        home_odds, draw_odds, away_odds = float(values["Home"]), float(values["Draw"]), float(values["Away"])
    except (TypeError, ValueError):
        return None

    over_2_5 = under_2_5 = None
    totals = _find_bet(bookmaker, "Goals Over/Under")
    if totals is not None:
        for v in totals.get("values", []) or []:
            try:
                if v.get("value") == "Over 2.5" and v.get("odd"):
                    over_2_5 = float(v["odd"])
                elif v.get("value") == "Under 2.5" and v.get("odd"):
                    under_2_5 = float(v["odd"])
            except (TypeError, ValueError):
                continue

    return {
        "bookmaker": bookmaker.get("name") or "unknown",
        "home_win_odds": home_odds, "draw_odds": draw_odds, "away_win_odds": away_odds,
        "over_2_5_odds": over_2_5, "under_2_5_odds": under_2_5,
    }


def parse_fixture_odds(fixture_payload: dict) -> dict | None:
    """One `response[]` entry -> a single best-available bookmaker quote.
    Same "prefer a bookmaker with both h2h and a 2.5 totals line, fall back
    to h2h alone" design the removed odds_live_source.py used (that choice
    was about models/blend.py needing the full 1X2+totals set to blend at
    all, not anything vendor-specific, so it carries over unchanged)."""
    teams = fixture_payload.get("teams") or {}
    home_name = (teams.get("home") or {}).get("name")
    away_name = (teams.get("away") or {}).get("name")
    kickoff = (fixture_payload.get("fixture") or {}).get("date")
    if not (home_name and away_name and kickoff):
        return None

    first_h2h_only = None
    for bookmaker in fixture_payload.get("bookmakers", []) or []:
        parsed = _parse_bookmaker(bookmaker)
        if parsed is None:
            continue
        entry = {**parsed, "home_team": home_name, "away_team": away_name, "commence_time": kickoff}
        if parsed["over_2_5_odds"] is not None and parsed["under_2_5_odds"] is not None:
            return entry
        if first_h2h_only is None:
            first_h2h_only = entry
    return first_h2h_only


def _cadence_minutes() -> float:
    return float(load_freshness().get("api_football_odds", 240))


def should_sync(conn, force: bool = False) -> tuple[bool, str]:
    """Real global cadence gate (`app_meta['api_football_odds_last_synced_at']`)
    - identical pattern to `solio_source.py::should_sync` - so this sync is
    safe to call on every `run_scheduled` tick regardless of how tight the
    real adaptive cadence gets; most ticks are a real no-op. This is the
    direct fix for the root-cause bug that got the prior connector's whole
    month's budget burned through in days."""
    if force:
        return True, "forced"
    row = conn.execute("SELECT value FROM app_meta WHERE key='api_football_odds_last_synced_at'").fetchone()
    if row is None:
        return True, "never synced"
    last = datetime.fromisoformat(row["value"])
    age_minutes = (datetime.now(timezone.utc) - last).total_seconds() / 60
    cadence = _cadence_minutes()
    if age_minutes >= cadence:
        return True, f"stale ({age_minutes:.0f}min >= {cadence:.0f}min cadence)"
    return False, f"fresh ({age_minutes:.0f}min old, cadence {cadence:.0f}min)"


def sync_api_football_odds(conn, force: bool = False) -> dict:
    """Real, cost-throttled entry point. One real request per distinct
    upcoming fixture date (never per fixture) within `_HORIZON_DAYS`, so a
    normal gameweek costs roughly 2-4 real requests per sync, not one per
    match."""
    do_sync, reason = should_sync(conn, force=force)
    if not do_sync:
        return {"skipped": True, "reason": reason, "matched": 0, "unmatched": 0, "failed": 0}

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=_HORIZON_DAYS)
    fixture_rows = conn.execute(
        "SELECT kickoff_time FROM fixtures WHERE finished=0 AND kickoff_time IS NOT NULL AND kickoff_time <= ?",
        (horizon.isoformat(),),
    ).fetchall()
    dates = sorted({row["kickoff_time"][:10] for row in fixture_rows if row["kickoff_time"] >= now.isoformat()[:10]})
    if not dates:
        return {"skipped": True, "reason": "no upcoming fixtures in horizon", "matched": 0, "unmatched": 0, "failed": 0}

    from fpl_agent.models.rules import current_season

    season_start_year = int(current_season(conn).split("-")[0])
    matched = unmatched = failed = 0
    retrieved_at = now.isoformat()
    try:
        for date in dates:
            for fixture_payload in fetch_odds_for_date(date, season_start_year):
                try:
                    parsed = parse_fixture_odds(fixture_payload)
                    if parsed is None:
                        unmatched += 1
                        continue
                    fixture_id = match_fixture_by_teams_and_kickoff(
                        conn, _SOURCE_NAME, parsed["home_team"], parsed["away_team"], parsed["commence_time"],
                    )
                    if fixture_id is None:
                        unmatched += 1
                        continue
                    conn.execute(
                        "INSERT INTO fixture_odds_live "
                        "(fixture_id, source, bookmaker, home_win_odds, draw_odds, away_win_odds, over_2_5_odds, under_2_5_odds, retrieved_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(fixture_id, source, bookmaker) DO UPDATE SET "
                        "home_win_odds=excluded.home_win_odds, draw_odds=excluded.draw_odds, away_win_odds=excluded.away_win_odds, "
                        "over_2_5_odds=excluded.over_2_5_odds, under_2_5_odds=excluded.under_2_5_odds, retrieved_at=excluded.retrieved_at",
                        (fixture_id, _SOURCE_NAME, parsed["bookmaker"], parsed["home_win_odds"], parsed["draw_odds"],
                         parsed["away_win_odds"], parsed["over_2_5_odds"], parsed["under_2_5_odds"], retrieved_at),
                    )
                    matched += 1
                except Exception:
                    failed += 1
                    continue
    except ApiFootballOddsFetchError as exc:
        update_source_health(conn, _SOURCE_NAME, success=False, error=str(exc))
        raise

    conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('api_football_odds_last_synced_at', ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (retrieved_at, retrieved_at),
    )
    conn.commit()

    error = f"{failed} fixture(s) failed to process" if failed else None
    update_source_health(conn, _SOURCE_NAME, success=(failed == 0), error=error)
    return {"skipped": False, "matched": matched, "unmatched": unmatched, "failed": failed, "dates_queried": len(dates)}
