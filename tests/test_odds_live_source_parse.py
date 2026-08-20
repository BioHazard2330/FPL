import requests
import pytest

from fpl_agent.ingestion.odds_live_source import OddsLiveFetchError, fetch_live_odds_payload, parse_live_odds_event

_SAMPLE_EVENT = {
    "id": "evt1",
    "home_team": "Arsenal",
    "away_team": "Chelsea",
    "commence_time": "2026-08-22T14:00:00Z",
    "bookmakers": [
        {
            "key": "bet365",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Chelsea", "price": 4.2},
                        {"name": "Draw", "price": 3.6},
                        {"name": "Arsenal", "price": 1.8},
                    ],
                },
                {
                    "key": "totals",
                    "outcomes": [
                        {"name": "Over", "price": 1.9, "point": 1.5},
                        {"name": "Under", "price": 1.9, "point": 1.5},
                        {"name": "Over", "price": 2.0, "point": 2.5},
                        {"name": "Under", "price": 1.8, "point": 2.5},
                    ],
                },
            ],
        },
        {
            "key": "williamhill",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": "Arsenal", "price": 1.75}, {"name": "Draw", "price": 3.7}, {"name": "Chelsea", "price": 4.3},
            ]}],
        },
    ],
}


def test_parse_live_odds_event_uses_first_bookmaker():
    parsed = parse_live_odds_event(_SAMPLE_EVENT)
    assert parsed["bookmaker"] == "bet365"


def test_parse_live_odds_event_matches_h2h_by_name_regardless_of_order():
    parsed = parse_live_odds_event(_SAMPLE_EVENT)
    assert parsed["home_win_odds"] == 1.8
    assert parsed["draw_odds"] == 3.6
    assert parsed["away_win_odds"] == 4.2


def test_parse_live_odds_event_filters_totals_to_2_5_line():
    parsed = parse_live_odds_event(_SAMPLE_EVENT)
    assert parsed["over_2_5_odds"] == 2.0
    assert parsed["under_2_5_odds"] == 1.8


def test_parse_live_odds_event_no_bookmakers_returns_none():
    event = dict(_SAMPLE_EVENT, bookmakers=[])
    assert parse_live_odds_event(event) is None


def test_parse_live_odds_event_no_totals_line_leaves_nulls():
    event = {
        **_SAMPLE_EVENT,
        "bookmakers": [{
            "key": "bet365",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": "Arsenal", "price": 1.8}, {"name": "Draw", "price": 3.6}, {"name": "Chelsea", "price": 4.2},
            ]}],
        }],
    }
    parsed = parse_live_odds_event(event)
    assert parsed is not None
    assert parsed["over_2_5_odds"] is None
    assert parsed["under_2_5_odds"] is None


def test_parse_live_odds_event_unmatched_h2h_outcome_returns_none():
    event = {
        **_SAMPLE_EVENT,
        "bookmakers": [{
            "key": "bet365",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": "Some Other Team", "price": 1.8}, {"name": "Draw", "price": 3.6}, {"name": "Chelsea", "price": 4.2},
            ]}],
        }],
    }
    assert parse_live_odds_event(event) is None


def test_fetch_live_odds_payload_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    with pytest.raises(OddsLiveFetchError, match="ODDS_API_KEY"):
        fetch_live_odds_payload()


_SECRET_API_KEY = "SECRET123ABC"


def test_fetch_live_odds_payload_error_never_leaks_api_key(monkeypatch):
    """Reproduces the original leak: requests' own HTTPError.__str__() (built by
    Response.raise_for_status()) includes the full request URL, which carries
    apiKey=<key> in cleartext. A 401 (invalid key) is the single most likely
    real-world failure a new user hits, so this constructs the error exactly the
    way raise_for_status() actually would - with a real response object whose .url
    carries the secret - to prove the raised OddsLiveFetchError's message is built
    from safe fields only, never from str(exc)."""
    monkeypatch.setenv("ODDS_API_KEY", _SECRET_API_KEY)

    response = requests.Response()
    response.status_code = 401
    response.reason = "Unauthorized"
    response.url = (
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/"
        f"?apiKey={_SECRET_API_KEY}&regions=uk&markets=h2h%2Ctotals&oddsFormat=decimal"
    )

    def fake_get(*args, **kwargs):
        return response

    monkeypatch.setattr("fpl_agent.ingestion.odds_live_source.requests.get", fake_get)

    with pytest.raises(OddsLiveFetchError) as excinfo:
        fetch_live_odds_payload()

    message = str(excinfo.value)
    assert _SECRET_API_KEY not in message
    assert "apiKey" not in message
    assert response.url not in message


def test_fetch_live_odds_payload_error_never_leaks_api_key_on_connection_failure(monkeypatch):
    """Connection-level failures (no response object at all) must also fall back to a
    fixed generic message rather than str(exc), since requests.ConnectionError can
    also embed the full request URL (with apiKey) in its own string form."""
    monkeypatch.setenv("ODDS_API_KEY", _SECRET_API_KEY)

    def fake_get(*args, **kwargs):
        raise requests.ConnectionError(
            f"Connection refused for url: https://api.the-odds-api.com/v4/sports/soccer_epl/odds/?apiKey={_SECRET_API_KEY}"
        )

    monkeypatch.setattr("fpl_agent.ingestion.odds_live_source.requests.get", fake_get)

    with pytest.raises(OddsLiveFetchError) as excinfo:
        fetch_live_odds_payload()

    message = str(excinfo.value)
    assert _SECRET_API_KEY not in message
    assert "apiKey" not in message
