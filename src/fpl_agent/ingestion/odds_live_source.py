"""Live pre-match odds for upcoming fixtures (the-odds-api.com free tier: 500
requests/day, no cost, requires a free API key - see .env.example). Feeds the
existing devig/blend math in models/odds_devig.py and models/blend.py, which
this module does not touch."""
import requests

from fpl_agent.config import get_odds_api_key

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
        raise OddsLiveFetchError(f"failed to fetch live odds: {exc}") from exc
    return resp.json()


def _find_market(bookmaker: dict, key: str) -> dict | None:
    for market in bookmaker.get("markets", []):
        if market.get("key") == key:
            return market
    return None


def parse_live_odds_event(event: dict) -> dict | None:
    bookmakers = event.get("bookmakers") or []
    if not bookmakers:
        return None
    bookmaker = bookmakers[0]

    h2h = _find_market(bookmaker, "h2h")
    if h2h is None:
        return None

    home_team, away_team = event["home_team"], event["away_team"]
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
        "commence_time": event["commence_time"],
        "bookmaker": bookmaker["key"],
        "home_win_odds": odds_by_name[home_team],
        "draw_odds": odds_by_name["Draw"],
        "away_win_odds": odds_by_name[away_team],
        "over_2_5_odds": over_2_5,
        "under_2_5_odds": under_2_5,
    }
