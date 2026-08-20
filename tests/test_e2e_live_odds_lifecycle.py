# tests/test_e2e_live_odds_lifecycle.py
"""One test chaining the real pipeline: sync (mocked API response, real DB
writes) -> fixture_odds_live rows -> models.expected_points reads them for an
unplayed fixture with no historical odds. Same bar every prior connector's E2E
test in this project sets."""
from fpl_agent.ingestion.odds_live_source import sync_live_odds
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.models.expected_points import _blended_fixture_goals
from fpl_agent.normalization.fpl_core import (
    normalize_element_types,
    normalize_events,
    normalize_players,
    normalize_teams,
)

from test_sync import make_bootstrap

_FEED = [{
    "id": "evt1", "home_team": "Arsenal", "away_team": "Chelsea",
    "commence_time": "2026-08-22T14:00:00Z",
    "bookmakers": [{"key": "bet365", "markets": [
        {"key": "h2h", "outcomes": [
            {"name": "Arsenal", "price": 1.5}, {"name": "Draw", "price": 4.5}, {"name": "Chelsea", "price": 6.0},
        ]},
        {"key": "totals", "outcomes": [
            {"name": "Over", "price": 1.8, "point": 2.5}, {"name": "Under", "price": 2.0, "point": 2.5},
        ]},
    ]}],
}]


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
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 1001, 1, '2026-08-22T14:00:00Z', 1, 2, 0, 0, '2026-08-20T00:00:00Z')"
    )
    db_conn.commit()

    import fpl_agent.ingestion.odds_live_source as odds_mod
    monkeypatch.setattr(odds_mod, "fetch_live_odds_payload", lambda: _FEED)

    result = sync_live_odds(db_conn)
    assert result["matched"] == 1

    team_goals, opp_goals = _blended_fixture_goals(db_conn, fixture_id=1, team_id=1, opponent_team_id=2, fixture_date="2026-08-22")
    # Arsenal heavily favored (1.5 odds) - blended home goals should exceed away goals.
    assert team_goals > opp_goals
