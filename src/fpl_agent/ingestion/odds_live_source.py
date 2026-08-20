"""Live pre-match odds for upcoming fixtures (the-odds-api.com free tier: 500
requests/day, no cost, requires a free API key - see .env.example). Feeds the
existing devig/blend math in models/odds_devig.py and models/blend.py, which
this module does not touch."""
from datetime import datetime, timezone

import requests

from fpl_agent.config import get_odds_api_key
from fpl_agent.ingestion.market_identity import get_or_create_market_team, normalize_common_team_name
from fpl_agent.ingestion.sync import update_source_health

_ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/"
_TIMEOUT_SECONDS = 15


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


_SOURCE_NAME = "odds_api"


def match_fixture(conn, home_team_name: str, away_team_name: str, commence_time: str) -> int | None:
    # the-odds-api.com returns clubs' full/formal names (e.g. "Manchester
    # United"), while FPL's own teams.name is its short display form (e.g.
    # "Man Utd") - get_or_create_market_team's fallback for a brand-new market
    # team only does an exact match against teams.name/short_name, so these
    # never resolve without help. Confirmed live 2026-08-20 against the real
    # API for GW1: 6 of 10 fixtures failed to match purely on this naming gap.
    # normalize_common_team_name (market_identity.py) is shared with
    # understat_source.py, which hit the same class of mismatch independently
    # the same day - centralized there rather than duplicated per-connector.
    home_market_id = get_or_create_market_team(conn, _SOURCE_NAME, normalize_common_team_name(home_team_name))
    away_market_id = get_or_create_market_team(conn, _SOURCE_NAME, normalize_common_team_name(away_team_name))

    home_row = conn.execute("SELECT fpl_team_id FROM market_teams WHERE id=?", (home_market_id,)).fetchone()
    away_row = conn.execute("SELECT fpl_team_id FROM market_teams WHERE id=?", (away_market_id,)).fetchone()
    if home_row is None or away_row is None or home_row["fpl_team_id"] is None or away_row["fpl_team_id"] is None:
        return None

    candidates = conn.execute(
        "SELECT id, kickoff_time FROM fixtures WHERE team_h=? AND team_a=? AND finished=0",
        (home_row["fpl_team_id"], away_row["fpl_team_id"]),
    ).fetchall()
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]["id"]

    # Rearranged/postponed fixtures have kickoff_time IS NULL - can't be compared to
    # commence_time, so they're excluded from disambiguation rather than crashing on
    # None.replace(). Zero comparable candidates left is a legitimate "can't
    # disambiguate" outcome (counted as unmatched by the caller), not a crash.
    dated_candidates = [row for row in candidates if row["kickoff_time"] is not None]
    if not dated_candidates:
        return None

    target = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))

    def _delta(row):
        kt = datetime.fromisoformat(row["kickoff_time"].replace("Z", "+00:00"))
        return abs((kt - target).total_seconds())

    return min(dated_candidates, key=_delta)["id"]


def sync_live_odds(conn) -> dict:
    try:
        payload = fetch_live_odds_payload()
    except OddsLiveFetchError as exc:
        update_source_health(conn, _SOURCE_NAME, success=False, error=str(exc))
        raise

    now = datetime.now(timezone.utc).isoformat()
    matched = unmatched = failed = 0

    for event in payload:
        # A single event's processing (match_fixture's disambiguation, or the insert)
        # raising an unexpected exception must not abort the whole run mid-loop and
        # discard every not-yet-committed insert from this run - one bad event is
        # counted and skipped, like a single manager-fetch failure in eo_sample.py or a
        # single malformed item in news_source.py, rather than crashing before the
        # commit or before update_source_health can record what actually happened.
        try:
            parsed = parse_live_odds_event(event)
            if parsed is None:
                unmatched += 1
                continue
            fixture_id = match_fixture(conn, parsed["home_team"], parsed["away_team"], parsed["commence_time"])
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

    conn.commit()

    # Unlike eo_sample.py's percentage tolerance (sized for ~750 sequential manager
    # fetches, where a couple of 404s is normal noise), a live-odds feed is a handful
    # of EPL fixtures per gameweek - any single event raising an unexpected exception
    # here is itself the noteworthy signal, not statistical noise. Report it as a
    # degraded run rather than silently reporting success=True.
    error = f"{failed} of {len(payload)} event(s) failed to process" if failed else None
    update_source_health(conn, _SOURCE_NAME, success=(failed == 0), error=error)
    return {"fetched": len(payload), "matched": matched, "unmatched": unmatched, "failed": failed}
