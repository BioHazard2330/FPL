"""Live pre-match odds for upcoming fixtures via the-odds-api.com (free tier:
500 CREDITS PER MONTH - not per day, a real, corrected mistake this module's
own docstring used to make). Feeds the existing devig/blend math in
models/odds_devig.py and models/blend.py, which this module does not touch.

Real history (2026-09-13): this module was removed once already after a
direct user report ("ran out of monthly credits and idk how") and replaced
with api-football.com. That replacement was itself removed the same day
after a real, live-verified dead end: api-football's free plan restricts
ALL data (not just odds) to seasons 2022-2024 - confirmed directly against
their real API with a real key, `{"errors": {"plan": "Free plans do not
have access to this season, try from 2022 to 2024."}}` - useless for a
live, current-season decision-support tool. Every other free alternative
checked the same day was also a real dead end: SportsGameOdds' free tier
excludes EPL (its own pricing page), odds-api.io's free tier has new
signups "paused indefinitely" (confirmed directly on their own live site),
Betfair Exchange's real-time API needs a real GBP 299 one-off fee.

So the-odds-api.com is real, restored - but the ACTUAL root cause of the
original problem was never "this vendor's free tier is too small," it was
that `sync_live_odds` had ZERO throttle of its own, firing on every single
`run_scheduled` tick (adaptive down to ~15min near a deadline per CLAUDE.md).
500 credits/month is genuinely enough for this project's real need (one
bulk call = 2 credits, covers every upcoming fixture at once) IF actually
throttled - a real, disclosed budget calculation: `should_sync`'s cadence
(`config/freshness.yaml`'s `odds_api` key, default 6h) means at most 4
calls/day = 8 credits/day = ~240 credits/month, well under the real 500
budget with margin for manual `fpl sync-live-odds` runs on top. This is the
one real, concrete fix this module was actually missing before - added via
the same `app_meta`-backed cadence-gate pattern `solio_source.py`/the
removed `api_football_odds_source.py` already used.

The real anytime-goalscorer PLAYER-PROP sync (`player_odds_source.py`) is
NOT restored alongside this - its own real per-fixture cost (1 credit per
fixture per fetch) shares the SAME monthly budget as this bulk call, and
reviving it at anywhere near its old cadence would blow straight through
the budget again even with a throttle. Left as a real, disclosed gap
(`models/expected_points.py::_market_blended_share` stays dormant, exactly
as before) rather than rebuilt without a genuinely safe cadence design."""
from datetime import datetime, timedelta, timezone

import requests

from fpl_agent.config import get_odds_api_key, load_freshness
from fpl_agent.ingestion.market_identity import match_fixture_by_teams_and_kickoff
from fpl_agent.ingestion.sync import update_source_health

_ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/"
_TIMEOUT_SECONDS = 15
_SOURCE_NAME = "odds_api"


class OddsLiveFetchError(Exception):
    pass


def fetch_live_odds_payload() -> list[dict]:
    api_key = get_odds_api_key()
    if not api_key:
        raise OddsLiveFetchError(
            "ODDS_API_KEY not set - see .env.example for how to configure a free the-odds-api.com key"
        )
    try:
        resp = requests.get(
            _ODDS_API_URL,
            params={"apiKey": api_key, "regions": "uk", "markets": "h2h,totals", "oddsFormat": "decimal"},
            timeout=_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        # Never interpolate str(exc) or exc's request/response objects here: requests'
        # own HTTPError/ConnectionError/Timeout __str__() includes the full request URL,
        # which carries apiKey=<the live key> in cleartext. This message is persisted
        # verbatim into source_health.last_error (readable via `fpl doctor` / a DB
        # backup) and echoed to CLI stderr, so it must be built only from known-safe
        # fields - never the exception's own string form.
        response = getattr(exc, "response", None)
        if response is not None:
            message = f"failed to fetch live odds: the-odds-api.com returned HTTP {response.status_code}"
        else:
            message = "failed to fetch live odds: request failed (see network logs)"
        raise OddsLiveFetchError(message) from exc
    return resp.json()


def _find_market(bookmaker: dict, key: str) -> dict | None:
    for market in bookmaker.get("markets", []):
        if market.get("key") == key:
            return market
    return None


def _parse_bookmaker(bookmaker: dict, home_team: str, away_team: str, commence_time: str) -> dict | None:
    h2h = _find_market(bookmaker, "h2h")
    if h2h is None:
        return None

    odds_by_name = {o["name"]: o["price"] for o in h2h.get("outcomes", [])}
    if home_team not in odds_by_name or away_team not in odds_by_name or "Draw" not in odds_by_name:
        return None

    over_2_5 = under_2_5 = None
    totals = _find_market(bookmaker, "totals")
    if totals is not None:
        for outcome in totals.get("outcomes", []):
            if outcome.get("point") != 2.5:
                continue
            if outcome.get("name") == "Over":
                over_2_5 = outcome["price"]
            elif outcome.get("name") == "Under":
                under_2_5 = outcome["price"]

    return {
        "home_team": home_team,
        "away_team": away_team,
        "commence_time": commence_time,
        "bookmaker": bookmaker["key"],
        "home_win_odds": odds_by_name[home_team],
        "draw_odds": odds_by_name["Draw"],
        "away_win_odds": odds_by_name[away_team],
        "over_2_5_odds": over_2_5,
        "under_2_5_odds": under_2_5,
    }


def parse_live_odds_event(event: dict) -> dict | None:
    """Picks one bookmaker's quote per event - still a single-bookmaker read, not an
    average (documented simplification, unchanged) - but prefers the first bookmaker
    that has BOTH a usable h2h market AND a 2.5 totals line, falling back to the
    first bookmaker with a usable h2h market alone. Plain "always take bookmakers[0]"
    was live-verified 2026-08-20 to leave every GW1 fixture's totals null (the
    earliest-listed UK bookmakers hadn't priced a 2.5 line yet this far from
    kickoff, even though several later ones already had) - since
    models/expected_points.py currently requires the full 1X2+totals set to blend
    at all, that meant zero fixtures ever actually blended despite odds being
    fetched and matched successfully. Searching for a complete bookmaker fixes
    that without changing the single-bookmaker (not averaged) design."""
    bookmakers = event.get("bookmakers") or []
    if not bookmakers:
        return None

    home_team, away_team = event["home_team"], event["away_team"]
    commence_time = event["commence_time"]

    first_h2h_only = None
    for bookmaker in bookmakers:
        parsed = _parse_bookmaker(bookmaker, home_team, away_team, commence_time)
        if parsed is None:
            continue
        if parsed["over_2_5_odds"] is not None and parsed["under_2_5_odds"] is not None:
            return parsed
        if first_h2h_only is None:
            first_h2h_only = parsed
    return first_h2h_only


def _cadence_minutes() -> float:
    return float(load_freshness().get("odds_api", 360))


def should_sync(conn, force: bool = False) -> tuple[bool, str]:
    """Real global cadence gate (`app_meta['odds_api_last_synced_at']`) -
    same pattern `solio_source.py::should_sync` already uses. This is the
    one concrete fix this module was actually missing before (see module
    docstring) - `sync_live_odds` is now safe to call on every
    `run_scheduled` tick regardless of how tight the real adaptive cadence
    gets; most ticks are a real no-op."""
    if force:
        return True, "forced"
    row = conn.execute("SELECT value FROM app_meta WHERE key='odds_api_last_synced_at'").fetchone()
    if row is None:
        return True, "never synced"
    last = datetime.fromisoformat(row["value"])
    age_minutes = (datetime.now(timezone.utc) - last).total_seconds() / 60
    cadence = _cadence_minutes()
    if age_minutes >= cadence:
        return True, f"stale ({age_minutes:.0f}min >= {cadence:.0f}min cadence)"
    return False, f"fresh ({age_minutes:.0f}min old, cadence {cadence:.0f}min)"


def sync_live_odds(conn, force: bool = False) -> dict:
    do_sync, reason = should_sync(conn, force=force)
    if not do_sync:
        return {"skipped": True, "reason": reason, "fetched": 0, "matched": 0, "unmatched": 0, "failed": 0}

    try:
        payload = fetch_live_odds_payload()
    except OddsLiveFetchError as exc:
        update_source_health(conn, _SOURCE_NAME, success=False, error=str(exc))
        raise

    now = datetime.now(timezone.utc).isoformat()
    matched = unmatched = failed = 0

    for event in payload:
        # A single event's processing (match_fixture_by_teams_and_kickoff's
        # disambiguation, or the insert) raising an unexpected exception must
        # not abort the whole run mid-loop and discard every not-yet-committed
        # insert from this run - one bad event is counted and skipped, like a
        # single manager-fetch failure in eo_sample.py or a single malformed
        # item in news_source.py, rather than crashing before the commit or
        # before update_source_health can record what actually happened.
        try:
            parsed = parse_live_odds_event(event)
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
                 parsed["away_win_odds"], parsed["over_2_5_odds"], parsed["under_2_5_odds"], now),
            )
            matched += 1
        except Exception:
            failed += 1
            continue

    conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('odds_api_last_synced_at', ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (now, now),
    )
    conn.commit()

    # Unlike eo_sample.py's percentage tolerance (sized for ~750 sequential manager
    # fetches, where a couple of 404s is normal noise), a live-odds feed is a handful
    # of EPL fixtures per gameweek - any single event raising an unexpected exception
    # here is itself the noteworthy signal, not statistical noise. Report it as a
    # degraded run rather than silently reporting success=True.
    error = f"{failed} of {len(payload)} event(s) failed to process" if failed else None
    update_source_health(conn, _SOURCE_NAME, success=(failed == 0), error=error)
    return {"skipped": False, "fetched": len(payload), "matched": matched, "unmatched": unmatched, "failed": failed}
