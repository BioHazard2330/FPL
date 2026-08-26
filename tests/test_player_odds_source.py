from datetime import datetime, timedelta, timezone

from fpl_agent.ingestion.player_odds_source import (
    PlayerOddsFetchError,
    parse_anytime_scorer_outcomes,
    sync_player_odds,
)
from test_odds_live_source_sync import _seed_two_teams_and_fixture

import fpl_agent.ingestion.player_odds_source as po_mod


def _seed_second_player(conn, player_id, team_id, web_name="Sample Forward"):
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
        "VALUES (?,?,?,?,1,'a',0,'t0')",
        (player_id, player_id, web_name, team_id),
    )
    conn.commit()


_EVENTS = [{"id": "evt1", "home_team": "Arsenal", "away_team": "Chelsea", "commence_time": "2026-08-22T14:00:00Z"}]

_ODDS_PAYLOAD = {
    "id": "evt1",
    "bookmakers": [{
        "key": "betfair_ex_uk",
        "markets": [{
            "key": "player_goal_scorer_anytime",
            "outcomes": [
                {"name": "Yes", "description": "Test Player", "price": 2.0},
                {"name": "Yes", "description": "Sample Forward", "price": 3.0},
                {"name": "No", "description": "Test Player", "price": 1.5},
            ],
        }],
    }],
}


def test_parse_anytime_scorer_outcomes_only_keeps_yes_rows():
    outcomes = parse_anytime_scorer_outcomes(_ODDS_PAYLOAD)
    assert len(outcomes) == 2
    assert all(o["price"] for o in outcomes)
    names = {o["player_name_raw"] for o in outcomes}
    assert names == {"Test Player", "Sample Forward"}


def test_parse_anytime_scorer_outcomes_empty_without_the_market():
    payload = {"bookmakers": [{"key": "x", "markets": [{"key": "h2h", "outcomes": []}]}]}
    assert parse_anytime_scorer_outcomes(payload) == []


def test_sync_player_odds_returns_zero_without_a_tracked_squad(db_conn):
    result = sync_player_odds(db_conn, set())
    assert result == {"fetched": 0, "skipped": 0, "failed": 0}
    result = sync_player_odds(db_conn, None)
    assert result == {"fetched": 0, "skipped": 0, "failed": 0}


def test_sync_player_odds_inserts_real_matched_rows(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn, kickoff=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat())
    _seed_second_player(db_conn, player_id=2, team_id=2)

    monkeypatch.setattr(po_mod, "fetch_upcoming_events", lambda: _EVENTS)
    monkeypatch.setattr(po_mod, "fetch_anytime_scorer_odds", lambda event_id: _ODDS_PAYLOAD)

    result = sync_player_odds(db_conn, {1})

    assert result["fetched"] == 1
    assert result["failed"] == 0
    rows = db_conn.execute("SELECT player_id, player_name_raw, anytime_scorer_price FROM player_odds_live ORDER BY player_id").fetchall()
    assert len(rows) == 2
    assert rows[0]["player_id"] == 1  # "Test Player" matched to player 1 (team_h)
    assert rows[1]["player_id"] == 2  # "Sample Forward" matched to player 2 (team_a)


def test_sync_player_odds_throttles_a_recently_fetched_fixture(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn, kickoff=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat())
    calls = {"n": 0}

    def fake_events():
        calls["n"] += 1
        return _EVENTS

    monkeypatch.setattr(po_mod, "fetch_upcoming_events", fake_events)
    monkeypatch.setattr(po_mod, "fetch_anytime_scorer_odds", lambda event_id: _ODDS_PAYLOAD)

    first = sync_player_odds(db_conn, {1})
    assert first["fetched"] == 1
    assert calls["n"] == 1

    second = sync_player_odds(db_conn, {1})
    assert second["fetched"] == 0
    assert second["skipped"] == 1
    # The real cost-conscious behavior: a fixture inside the freshness window
    # never even triggers the events-list network call.
    assert calls["n"] == 1


def test_sync_player_odds_ignores_fixtures_beyond_the_real_near_term_window(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn, kickoff=(datetime.now(timezone.utc) + timedelta(days=60)).isoformat())
    monkeypatch.setattr(po_mod, "fetch_upcoming_events", lambda: _EVENTS)
    monkeypatch.setattr(po_mod, "fetch_anytime_scorer_odds", lambda event_id: _ODDS_PAYLOAD)

    result = sync_player_odds(db_conn, {1})

    assert result == {"fetched": 0, "skipped": 0, "failed": 0}


def test_sync_player_odds_raises_without_an_api_key(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn, kickoff=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat())
    monkeypatch.setattr(po_mod, "get_odds_api_key", lambda: None)

    try:
        sync_player_odds(db_conn, {1})
        assert False, "expected PlayerOddsFetchError"
    except PlayerOddsFetchError:
        pass
