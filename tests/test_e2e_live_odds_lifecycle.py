# tests/test_e2e_live_odds_lifecycle.py
"""One test chaining the real pipeline: sync (mocked API response, real DB
writes) -> fixture_odds_live rows -> models.expected_points reads them for an
unplayed fixture with no historical odds. Same bar every prior connector's E2E
test in this project sets. Re-platformed 2026-09-13 onto api_football_odds_
source.py (the-odds-api.com-based connector removed - real free tier turned
out to be 500 credits/MONTH, not per day, with no throttle at this call site)."""
from datetime import datetime, timedelta, timezone

from fpl_agent.ingestion.api_football_odds_source import sync_api_football_odds
from fpl_agent.ingestion.sync import _extract_season, _upsert_many, sync_rules
from fpl_agent.models.expected_points import _blended_fixture_goals
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

_FIXTURE_PAYLOAD = {
    "fixture": {"id": 999111, "date": _KICKOFF_ISO},
    "teams": {"home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}},
    "bookmakers": [{
        "name": "Bet365",
        "bets": [
            {"name": "Match Winner", "values": [
                {"value": "Home", "odd": "1.5"}, {"value": "Draw", "odd": "4.5"}, {"value": "Away", "odd": "6.0"},
            ]},
            {"name": "Goals Over/Under", "values": [
                {"value": "Over 2.5", "odd": "1.8"}, {"value": "Under 2.5", "odd": "2.0"},
            ]},
        ],
    }],
}


def test_full_live_odds_lifecycle_composes_without_error(db_conn, monkeypatch):
    bootstrap = make_bootstrap()
    bootstrap["teams"][0].update({"id": 1, "name": "Arsenal", "short_name": "ARS"})
    bootstrap["teams"].append({
        "id": 2, "code": 4, "name": "Chelsea", "short_name": "CHE",
        "strength_overall_home": 3, "strength_overall_away": 3,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(db_conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(db_conn, "events", normalize_events(bootstrap), "t0")
    _upsert_many(db_conn, "players", normalize_players(bootstrap), "t0")
    sync_rules(db_conn, flatten_rules(bootstrap), _extract_season(bootstrap), "fpl_api_bootstrap", "t0")
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 1001, 1, ?, 1, 2, 0, 0, '2026-08-20T00:00:00Z')",
        (_KICKOFF_ISO,),
    )
    db_conn.commit()

    import fpl_agent.ingestion.api_football_odds_source as mod
    monkeypatch.setattr(mod, "fetch_odds_for_date", lambda date, season: [_FIXTURE_PAYLOAD])

    result = sync_api_football_odds(db_conn)
    assert result["matched"] == 1

    fixture_date = _KICKOFF_ISO[:10]
    team_goals, opp_goals = _blended_fixture_goals(db_conn, fixture_id=1, team_id=1, opponent_team_id=2, fixture_date=fixture_date)
    # Arsenal heavily favored (1.5 odds) - blended home goals should exceed away goals.
    assert team_goals > opp_goals
