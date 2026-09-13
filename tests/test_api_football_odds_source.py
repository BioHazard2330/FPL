from datetime import datetime, timedelta, timezone

import requests
import pytest

from fpl_agent.ingestion.api_football_odds_source import (
    ApiFootballOddsFetchError,
    fetch_odds_for_date,
    parse_fixture_odds,
    should_sync,
    sync_api_football_odds,
)
from fpl_agent.ingestion.sync import _extract_season, _upsert_many, sync_rules
from fpl_agent.normalization.fpl_core import (
    flatten_rules,
    normalize_element_types,
    normalize_events,
    normalize_players,
    normalize_teams,
)

from test_sync import make_bootstrap

_KICKOFF = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
_KICKOFF_ISO = _KICKOFF.isoformat().replace("+00:00", "Z")
_KICKOFF_DATE = _KICKOFF_ISO[:10]


def _seed_two_teams_and_fixture(conn, fixture_id=1, kickoff=_KICKOFF_ISO, finished=0):
    bootstrap = make_bootstrap()
    bootstrap["teams"][0].update({"id": 1, "name": "Arsenal", "short_name": "ARS"})
    bootstrap["teams"].append({
        "id": 2, "code": 4, "name": "Chelsea", "short_name": "CHE",
        "strength_overall_home": 3, "strength_overall_away": 3,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "events", normalize_events(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    sync_rules(conn, flatten_rules(bootstrap), _extract_season(bootstrap), "fpl_api_bootstrap", "t0")
    conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (?, ?, 1, ?, 1, 2, ?, 0, '2026-08-20T00:00:00Z')",
        (fixture_id, 1000 + fixture_id, kickoff, finished),
    )
    conn.commit()


_SAMPLE_FIXTURE = {
    "fixture": {"id": 999111, "date": _KICKOFF_ISO},
    "teams": {"home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}},
    "bookmakers": [
        {
            "name": "Bet365",
            "bets": [
                {"name": "Match Winner", "values": [
                    {"value": "Home", "odd": "1.80"}, {"value": "Draw", "odd": "3.60"}, {"value": "Away", "odd": "4.20"},
                ]},
                {"name": "Goals Over/Under", "values": [
                    {"value": "Over 1.5", "odd": "1.20"}, {"value": "Under 1.5", "odd": "4.00"},
                    {"value": "Over 2.5", "odd": "2.00"}, {"value": "Under 2.5", "odd": "1.80"},
                ]},
            ],
        },
        {
            "name": "William Hill",
            "bets": [
                {"name": "Match Winner", "values": [
                    {"value": "Home", "odd": "1.77"}, {"value": "Draw", "odd": "3.70"}, {"value": "Away", "odd": "4.30"},
                ]},
            ],
        },
    ],
}


def test_parse_fixture_odds_prefers_a_bookmaker_with_both_h2h_and_totals():
    parsed = parse_fixture_odds(_SAMPLE_FIXTURE)
    assert parsed["bookmaker"] == "Bet365"
    assert parsed["home_win_odds"] == 1.80
    assert parsed["draw_odds"] == 3.60
    assert parsed["away_win_odds"] == 4.20
    assert parsed["over_2_5_odds"] == 2.00
    assert parsed["under_2_5_odds"] == 1.80
    assert parsed["home_team"] == "Arsenal" and parsed["away_team"] == "Chelsea"


def test_parse_fixture_odds_falls_back_to_h2h_only_when_none_have_totals():
    fixture = {**_SAMPLE_FIXTURE, "bookmakers": [_SAMPLE_FIXTURE["bookmakers"][1]]}
    parsed = parse_fixture_odds(fixture)
    assert parsed["bookmaker"] == "William Hill"
    assert parsed["over_2_5_odds"] is None
    assert parsed["under_2_5_odds"] is None


def test_parse_fixture_odds_returns_none_without_a_match_winner_bet():
    fixture = {
        "fixture": {"id": 1, "date": _KICKOFF_ISO},
        "teams": {"home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}},
        "bookmakers": [{"name": "Bet365", "bets": [{"name": "Both Teams To Score", "values": []}]}],
    }
    assert parse_fixture_odds(fixture) is None


def test_parse_fixture_odds_returns_none_without_teams_or_kickoff():
    assert parse_fixture_odds({"fixture": {"id": 1}, "teams": {}, "bookmakers": []}) is None


def test_parse_fixture_odds_tolerates_an_unparseable_odd_value():
    fixture = {
        "fixture": {"id": 1, "date": _KICKOFF_ISO},
        "teams": {"home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}},
        "bookmakers": [{"name": "Bet365", "bets": [{"name": "Match Winner", "values": [
            {"value": "Home", "odd": "N/A"}, {"value": "Draw", "odd": "3.60"}, {"value": "Away", "odd": "4.20"},
        ]}]}],
    }
    assert parse_fixture_odds(fixture) is None


def test_fetch_odds_for_date_raises_without_an_api_key(monkeypatch):
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    with pytest.raises(ApiFootballOddsFetchError, match="API_FOOTBALL_KEY"):
        fetch_odds_for_date("2026-08-22", 2026)


_SECRET_API_KEY = "SECRET123ABC"


def test_fetch_odds_for_date_error_never_leaks_the_api_key(monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", _SECRET_API_KEY)

    response = requests.Response()
    response.status_code = 401
    response.reason = "Unauthorized"
    response.url = f"https://v3.football.api-sports.io/odds?league=39&season=2026&date=2026-08-22"
    response.request = requests.PreparedRequest()
    response.request.headers = {"x-apisports-key": _SECRET_API_KEY}

    def fake_get(*args, **kwargs):
        return response

    monkeypatch.setattr("fpl_agent.ingestion.api_football_odds_source.requests.get", fake_get)

    with pytest.raises(ApiFootballOddsFetchError) as excinfo:
        fetch_odds_for_date("2026-08-22", 2026)

    assert _SECRET_API_KEY not in str(excinfo.value)


def test_should_sync_true_when_never_synced(db_conn):
    do_sync, reason = should_sync(db_conn)
    assert do_sync is True
    assert "never synced" in reason


def test_should_sync_false_within_the_cadence_window(db_conn):
    now = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('api_football_odds_last_synced_at', ?, ?)",
        (now, now),
    )
    db_conn.commit()
    do_sync, reason = should_sync(db_conn)
    assert do_sync is False
    assert "fresh" in reason


def test_should_sync_true_when_forced_even_if_fresh(db_conn):
    now = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('api_football_odds_last_synced_at', ?, ?)",
        (now, now),
    )
    db_conn.commit()
    do_sync, reason = should_sync(db_conn, force=True)
    assert do_sync is True
    assert reason == "forced"


def test_sync_api_football_odds_inserts_a_real_matched_row(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn)
    import fpl_agent.ingestion.api_football_odds_source as mod

    monkeypatch.setattr(mod, "fetch_odds_for_date", lambda date, season: [_SAMPLE_FIXTURE])

    result = sync_api_football_odds(db_conn)

    assert result["skipped"] is False
    assert result["matched"] == 1
    assert result["dates_queried"] == 1
    row = db_conn.execute("SELECT * FROM fixture_odds_live WHERE fixture_id=1 AND source='api_football'").fetchone()
    assert row["home_win_odds"] == 1.80


def test_sync_api_football_odds_skips_within_the_cadence_window(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn)
    import fpl_agent.ingestion.api_football_odds_source as mod

    calls = {"n": 0}

    def fake_fetch(date, season):
        calls["n"] += 1
        return [_SAMPLE_FIXTURE]

    monkeypatch.setattr(mod, "fetch_odds_for_date", fake_fetch)

    first = sync_api_football_odds(db_conn)
    assert first["skipped"] is False
    assert calls["n"] == 1

    second = sync_api_football_odds(db_conn)
    assert second["skipped"] is True
    # The real cost-conscious behavior: a fresh sync never even triggers the
    # network call - this is the direct fix for the root-cause bug (the
    # removed the-odds-api.com connector had no such gate at all).
    assert calls["n"] == 1


def test_sync_api_football_odds_returns_no_upcoming_fixtures_without_crashing(db_conn):
    result = sync_api_football_odds(db_conn)
    assert result == {"skipped": True, "reason": "no upcoming fixtures in horizon", "matched": 0, "unmatched": 0, "failed": 0}


def test_sync_api_football_odds_counts_unmatched_fixtures(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn)
    import fpl_agent.ingestion.api_football_odds_source as mod

    unmatched_fixture = {
        **_SAMPLE_FIXTURE,
        "teams": {"home": {"name": "Nonexistent FC"}, "away": {"name": "Also Nonexistent"}},
    }
    monkeypatch.setattr(mod, "fetch_odds_for_date", lambda date, season: [_SAMPLE_FIXTURE, unmatched_fixture])

    result = sync_api_football_odds(db_conn)

    assert result["matched"] == 1
    assert result["unmatched"] == 1


def test_sync_api_football_odds_tolerates_a_single_crashing_fixture(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn)
    import fpl_agent.ingestion.api_football_odds_source as mod

    real_parse = mod.parse_fixture_odds
    call_count = {"n": 0}

    def flaky_parse(fixture_payload):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated crash")
        return real_parse(fixture_payload)

    monkeypatch.setattr(mod, "fetch_odds_for_date", lambda date, season: [_SAMPLE_FIXTURE, _SAMPLE_FIXTURE])
    monkeypatch.setattr(mod, "parse_fixture_odds", flaky_parse)

    result = sync_api_football_odds(db_conn)

    # The first (crashing) fixture is counted as failed; the second, identical
    # payload still resolves and gets committed - one bad item never aborts the run.
    assert result["failed"] == 1
    assert result["matched"] == 1


def test_sync_api_football_odds_propagates_a_real_fetch_error(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn)
    import fpl_agent.ingestion.api_football_odds_source as mod

    def raise_error(date, season):
        raise ApiFootballOddsFetchError("failed to fetch match odds: api-football.com returned HTTP 401")

    monkeypatch.setattr(mod, "fetch_odds_for_date", raise_error)

    with pytest.raises(ApiFootballOddsFetchError):
        sync_api_football_odds(db_conn)

    health = db_conn.execute("SELECT * FROM source_health WHERE source_name='api_football'").fetchone()
    assert health["failure_count"] == 1
