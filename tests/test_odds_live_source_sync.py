from fpl_agent.ingestion.odds_live_source import match_fixture, sync_live_odds
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import (
    normalize_element_types,
    normalize_events,
    normalize_players,
    normalize_teams,
)

from test_sync import make_bootstrap


def _seed_two_teams_and_fixture(conn, fixture_id=1, kickoff="2026-08-22T14:00:00Z", finished=0):
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
    conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (?, ?, 1, ?, 1, 2, ?, 0, '2026-08-20T00:00:00Z')",
        (fixture_id, 1000 + fixture_id, kickoff, finished),
    )
    conn.commit()


def test_match_fixture_finds_the_right_unplayed_fixture(db_conn):
    _seed_two_teams_and_fixture(db_conn)
    fixture_id = match_fixture(db_conn, "Arsenal", "Chelsea", "2026-08-22T14:00:00Z")
    assert fixture_id == 1


def test_match_fixture_returns_none_for_unresolvable_team(db_conn):
    _seed_two_teams_and_fixture(db_conn)
    assert match_fixture(db_conn, "Arsenal", "Some Nonexistent FC", "2026-08-22T14:00:00Z") is None


def test_match_fixture_disambiguates_double_fixture_by_closest_kickoff(db_conn):
    _seed_two_teams_and_fixture(db_conn, fixture_id=1, kickoff="2026-08-22T14:00:00Z")
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (2, 1002, 1, '2026-09-15T14:00:00Z', 1, 2, 0, 0, '2026-08-20T00:00:00Z')"
    )
    db_conn.commit()
    fixture_id = match_fixture(db_conn, "Arsenal", "Chelsea", "2026-08-22T15:00:00Z")
    assert fixture_id == 1  # closer to this kickoff than the Sept fixture


_FEED = [
    {
        "id": "evt1", "home_team": "Arsenal", "away_team": "Chelsea",
        "commence_time": "2026-08-22T14:00:00Z",
        "bookmakers": [{"key": "bet365", "markets": [
            {"key": "h2h", "outcomes": [
                {"name": "Arsenal", "price": 1.8}, {"name": "Draw", "price": 3.6}, {"name": "Chelsea", "price": 4.2},
            ]},
        ]}],
    },
]


def test_sync_live_odds_inserts_matched_row(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn)
    import fpl_agent.ingestion.odds_live_source as odds_mod
    monkeypatch.setattr(odds_mod, "fetch_live_odds_payload", lambda: _FEED)

    result = sync_live_odds(db_conn)

    assert result == {"fetched": 1, "matched": 1, "unmatched": 0}
    row = db_conn.execute("SELECT * FROM fixture_odds_live WHERE fixture_id=1").fetchone()
    assert row["home_win_odds"] == 1.8


def test_sync_live_odds_upserts_on_rerun(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn)
    import fpl_agent.ingestion.odds_live_source as odds_mod
    monkeypatch.setattr(odds_mod, "fetch_live_odds_payload", lambda: _FEED)

    sync_live_odds(db_conn)
    sync_live_odds(db_conn)

    rows = db_conn.execute("SELECT * FROM fixture_odds_live").fetchall()
    assert len(rows) == 1  # updated in place, not duplicated


def test_sync_live_odds_counts_unmatched_events(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn)
    unmatched_feed = _FEED + [{
        "id": "evt2", "home_team": "Nonexistent FC", "away_team": "Also Nonexistent",
        "commence_time": "2026-08-22T14:00:00Z",
        "bookmakers": [{"key": "bet365", "markets": [
            {"key": "h2h", "outcomes": [
                {"name": "Nonexistent FC", "price": 1.8}, {"name": "Draw", "price": 3.6}, {"name": "Also Nonexistent", "price": 4.2},
            ]},
        ]}],
    }]
    import fpl_agent.ingestion.odds_live_source as odds_mod
    monkeypatch.setattr(odds_mod, "fetch_live_odds_payload", lambda: unmatched_feed)

    result = sync_live_odds(db_conn)
    assert result == {"fetched": 2, "matched": 1, "unmatched": 1}
