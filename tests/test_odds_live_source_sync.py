from datetime import datetime, timedelta, timezone

from fpl_agent.ingestion.odds_live_source import should_sync, sync_live_odds
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


def test_should_sync_true_when_never_synced(db_conn):
    do_sync, reason = should_sync(db_conn)
    assert do_sync is True
    assert "never synced" in reason


def test_should_sync_false_within_the_cadence_window(db_conn):
    now = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('odds_api_last_synced_at', ?, ?)",
        (now, now),
    )
    db_conn.commit()
    do_sync, reason = should_sync(db_conn)
    assert do_sync is False
    assert "fresh" in reason


def test_should_sync_true_when_stale(db_conn):
    stale = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('odds_api_last_synced_at', ?, ?)",
        (stale, stale),
    )
    db_conn.commit()
    do_sync, reason = should_sync(db_conn)
    assert do_sync is True
    assert "stale" in reason


def test_should_sync_true_when_forced_even_if_fresh(db_conn):
    now = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('odds_api_last_synced_at', ?, ?)",
        (now, now),
    )
    db_conn.commit()
    do_sync, reason = should_sync(db_conn, force=True)
    assert do_sync is True
    assert reason == "forced"


def test_sync_live_odds_inserts_matched_row(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn)
    import fpl_agent.ingestion.odds_live_source as odds_mod
    monkeypatch.setattr(odds_mod, "fetch_live_odds_payload", lambda: _FEED)

    result = sync_live_odds(db_conn)

    assert result == {"skipped": False, "fetched": 1, "matched": 1, "unmatched": 0, "failed": 0}
    row = db_conn.execute("SELECT * FROM fixture_odds_live WHERE fixture_id=1").fetchone()
    assert row["home_win_odds"] == 1.8


def test_sync_live_odds_upserts_on_rerun(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn)
    import fpl_agent.ingestion.odds_live_source as odds_mod
    monkeypatch.setattr(odds_mod, "fetch_live_odds_payload", lambda: _FEED)

    sync_live_odds(db_conn, force=True)
    sync_live_odds(db_conn, force=True)

    rows = db_conn.execute("SELECT * FROM fixture_odds_live").fetchall()
    assert len(rows) == 1  # updated in place, not duplicated


def test_sync_live_odds_skips_within_the_cadence_window(db_conn, monkeypatch):
    _seed_two_teams_and_fixture(db_conn)
    import fpl_agent.ingestion.odds_live_source as odds_mod

    calls = {"n": 0}

    def fake_fetch():
        calls["n"] += 1
        return _FEED

    monkeypatch.setattr(odds_mod, "fetch_live_odds_payload", fake_fetch)

    first = sync_live_odds(db_conn)
    assert first["skipped"] is False
    assert calls["n"] == 1

    second = sync_live_odds(db_conn)
    assert second["skipped"] is True
    # The real cost-conscious behavior this connector was originally missing:
    # a fresh sync never even triggers the network call.
    assert calls["n"] == 1


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
    assert result == {"skipped": False, "fetched": 2, "matched": 1, "unmatched": 1, "failed": 0}


def test_sync_live_odds_tolerates_single_crashing_event(db_conn, monkeypatch):
    # A single event's processing raising an unexpected exception (not just the
    # already-fixed NULL-kickoff case - any bad event) must not abort the whole run:
    # the other, valid event in the same feed still gets matched and committed, and
    # the run's degradation is honestly reflected in both the return value and
    # source_health rather than silently reporting success.
    _seed_two_teams_and_fixture(db_conn)
    crash_feed = _FEED + [{
        "id": "evt2", "home_team": "Arsenal", "away_team": "Chelsea",
        "commence_time": "2026-08-22T14:00:00Z",
        "bookmakers": [{"key": "bet365", "markets": [
            {"key": "h2h", "outcomes": [
                {"name": "Arsenal", "price": 1.9}, {"name": "Draw", "price": 3.5}, {"name": "Chelsea", "price": 4.0},
            ]},
        ]}],
    }]
    import fpl_agent.ingestion.odds_live_source as odds_mod
    monkeypatch.setattr(odds_mod, "fetch_live_odds_payload", lambda: crash_feed)

    real_match_fixture = odds_mod.match_fixture_by_teams_and_kickoff
    call_count = {"n": 0}

    def flaky_match_fixture(conn, source, home_team, away_team, commence_time):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated crash processing this event")
        return real_match_fixture(conn, source, home_team, away_team, commence_time)

    monkeypatch.setattr(odds_mod, "match_fixture_by_teams_and_kickoff", flaky_match_fixture)

    result = sync_live_odds(db_conn)

    assert result == {"skipped": False, "fetched": 2, "matched": 1, "unmatched": 0, "failed": 1}
    # the second, valid event still got processed and committed despite the first crashing
    row = db_conn.execute("SELECT * FROM fixture_odds_live WHERE fixture_id=1").fetchone()
    assert row is not None

    health = db_conn.execute("SELECT * FROM source_health WHERE source_name='odds_api'").fetchone()
    assert health["failure_count"] == 1
    assert "1 of 2" in health["last_error"]
