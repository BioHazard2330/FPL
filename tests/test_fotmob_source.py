from datetime import date

import pytest

import fpl_agent.ingestion.fotmob_source as fotmob_mod
from datetime import datetime, timedelta, timezone

from fpl_agent.ingestion.fotmob_source import (
    FotMobFetchError,
    find_match,
    refresh_in_progress_matches,
    sync_match,
)
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import (
    normalize_element_types,
    normalize_events,
    normalize_players,
    normalize_teams,
)

from test_sync import make_bootstrap

_MATCHES_PAYLOAD = {
    "leagues": [
        {
            "name": "Premier League",
            "matches": [
                {"id": 5795363, "home": {"name": "Arsenal"}, "away": {"name": "Coventry"},
                 "status": {"utcTime": "2026-08-21T19:00:00.000Z"}},
            ],
        },
        {
            "name": "Other League",
            "matches": [
                {"id": 999, "home": {"name": "Some Team"}, "away": {"name": "Another"},
                 "status": {"utcTime": "2026-08-21T15:00:00.000Z"}},
            ],
        },
    ]
}

_DETAILS_PAYLOAD = {
    "general": {
        "matchId": "5795363", "leagueName": "Premier League",
        "matchTimeUTCDate": "2026-08-21T19:00:00.000Z",
        "homeTeam": {"name": "Arsenal", "id": 9825},
        "awayTeam": {"name": "Coventry City", "id": 8669},
        "started": False, "finished": False,
    },
    "header": {
        "teams": [{"name": "Arsenal", "id": 9825, "score": 0}, {"name": "Coventry City", "id": 8669, "score": 0}],
        "status": {"started": False, "finished": False},
    },
    "content": {
        "lineup": {
            "homeTeam": {"id": 9825, "name": "Arsenal", "formation": "4-3-3",
                         "starters": [{"id": 1, "name": "Test Player"}]},
            "awayTeam": {"id": 8669, "name": "Coventry City", "formation": "4-4-2",
                         "starters": [{"id": 2, "name": "Unknown FotMob Player"}]},
        },
        "stats": None,
        "shotmap": {"shots": [], "Periods": {"All": []}},
    },
}


def _seed(conn):
    bootstrap = make_bootstrap()
    bootstrap["teams"].append({
        "id": 2, "code": 7, "name": "Coventry City", "short_name": "COV",
        "strength_overall_home": 2, "strength_overall_away": 2,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "events", normalize_events(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 1001, 1, '2026-08-21T19:00:00Z', 1, 2, 0, 0, '2026-08-20T00:00:00Z')"
    )
    conn.commit()


def test_find_match_resolves_real_fixture_without_hardcoded_id(monkeypatch):
    monkeypatch.setattr(fotmob_mod, "fetch_matches_for_date", lambda d: _MATCHES_PAYLOAD)
    match_id = find_match(date(2026, 8, 21), "Arsenal", "Coventry")
    assert match_id == "5795363"


def test_find_match_returns_none_when_not_found(monkeypatch):
    monkeypatch.setattr(fotmob_mod, "fetch_matches_for_date", lambda d: _MATCHES_PAYLOAD)
    assert find_match(date(2026, 8, 21), "Nonexistent FC", "Nobody") is None


def test_sync_match_upserts_match_player_and_team_state(monkeypatch, db_conn):
    _seed(db_conn)
    monkeypatch.setattr(fotmob_mod, "find_match", lambda day, h, a: "5795363")
    monkeypatch.setattr(fotmob_mod, "fetch_match_details", lambda mid: _DETAILS_PAYLOAD)
    monkeypatch.setattr(fotmob_mod, "save_raw", lambda name, data: "raw/path.json")

    result = sync_match(db_conn, "Arsenal", "Coventry", date(2026, 8, 21))

    assert result["fotmob_match_id"] == "5795363"
    assert result["status"] == "PRE_MATCH"
    assert result["kickoff_utc"] == "2026-08-21T19:00:00.000Z"
    assert result["players_ingested"] == 2
    # "Test Player" resolves against the seeded player (web_name="Test Player");
    # the unknown FotMob player must NOT be dropped or crash - stored unresolved.
    assert result["players_resolved"] == 1

    match_row = db_conn.execute(
        "SELECT * FROM match_intelligence WHERE fotmob_match_id='5795363'"
    ).fetchone()
    assert match_row["home_team_id"] == 1
    assert match_row["away_team_id"] == 2
    assert match_row["fpl_fixture_id"] == 1
    assert match_row["source"] == "fotmob"
    assert match_row["retrieved_at"] is not None

    player_rows = db_conn.execute(
        "SELECT * FROM player_match_state WHERE match_id=?", (match_row["id"],)
    ).fetchall()
    assert len(player_rows) == 2
    resolved = next(r for r in player_rows if r["fotmob_player_id"] == "1")
    assert resolved["player_id"] == 1
    unresolved = next(r for r in player_rows if r["fotmob_player_id"] == "2")
    assert unresolved["player_id"] is None  # never fabricated

    team_rows = db_conn.execute(
        "SELECT * FROM team_match_state WHERE match_id=?", (match_row["id"],)
    ).fetchall()
    assert len(team_rows) == 2
    assert {r["formation"] for r in team_rows} == {"4-3-3", "4-4-2"}


def test_sync_match_is_idempotent_and_updates_in_place(monkeypatch, db_conn):
    _seed(db_conn)
    monkeypatch.setattr(fotmob_mod, "find_match", lambda day, h, a: "5795363")
    monkeypatch.setattr(fotmob_mod, "fetch_match_details", lambda mid: _DETAILS_PAYLOAD)
    monkeypatch.setattr(fotmob_mod, "save_raw", lambda name, data: "raw/path.json")

    sync_match(db_conn, "Arsenal", "Coventry", date(2026, 8, 21))
    sync_match(db_conn, "Arsenal", "Coventry", date(2026, 8, 21))

    count = db_conn.execute("SELECT COUNT(*) c FROM match_intelligence").fetchone()["c"]
    assert count == 1


def test_sync_match_raises_and_leaves_prior_state_untouched_on_fetch_failure(monkeypatch, db_conn):
    _seed(db_conn)
    monkeypatch.setattr(fotmob_mod, "find_match", lambda day, h, a: "5795363")
    monkeypatch.setattr(fotmob_mod, "fetch_match_details", lambda mid: _DETAILS_PAYLOAD)
    monkeypatch.setattr(fotmob_mod, "save_raw", lambda name, data: "raw/path.json")
    sync_match(db_conn, "Arsenal", "Coventry", date(2026, 8, 21))

    def _boom(mid):
        raise FotMobFetchError("fotmob request failed: HTTP 500 (test)")

    monkeypatch.setattr(fotmob_mod, "fetch_match_details", _boom)
    with pytest.raises(FotMobFetchError):
        sync_match(db_conn, "Arsenal", "Coventry", date(2026, 8, 21))

    row = db_conn.execute("SELECT * FROM match_intelligence WHERE fotmob_match_id='5795363'").fetchone()
    assert row["status"] == "PRE_MATCH"  # untouched, not blanked

    health = db_conn.execute(
        "SELECT * FROM source_health WHERE source_name='fotmob'"
    ).fetchone()
    assert health["failure_count"] >= 1


def test_sync_match_raises_when_no_fixture_resolvable(monkeypatch, db_conn):
    _seed(db_conn)
    monkeypatch.setattr(fotmob_mod, "find_match", lambda day, h, a: None)
    with pytest.raises(FotMobFetchError):
        sync_match(db_conn, "Nonexistent", "Team", date(2026, 8, 21))


# --- refresh_in_progress_matches (Slice A2 automatic post-match trigger) --


def _seed_match_intelligence_row(conn, status, kickoff: datetime):
    _seed(conn)
    conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "home_score, away_score, source, retrieved_at, confidence) "
        "VALUES ('5795363','Premier League',?,1,2,?,NULL,NULL,'fotmob','2026-08-21T15:00:00+00:00','high')",
        (kickoff.isoformat().replace("+00:00", "Z"), status),
    )
    conn.commit()


def test_refresh_in_progress_matches_refreshes_a_recent_non_final_match(monkeypatch, db_conn):
    kickoff = datetime.now(timezone.utc) - timedelta(hours=2)
    _seed_match_intelligence_row(db_conn, "LIVE", kickoff)

    calls = []
    monkeypatch.setattr(fotmob_mod, "find_match", lambda day, h, a: "5795363")
    monkeypatch.setattr(fotmob_mod, "fetch_match_details", lambda mid: _DETAILS_PAYLOAD)
    monkeypatch.setattr(fotmob_mod, "save_raw", lambda name, data: "raw/path.json")
    real_sync = fotmob_mod.sync_match

    def spy(conn, home, away, day):
        calls.append((home, away))
        return real_sync(conn, home, away, day)

    monkeypatch.setattr(fotmob_mod, "sync_match", spy)

    result = refresh_in_progress_matches(db_conn)

    assert result["refreshed"] == 1
    assert result["failed"] == 0
    assert len(calls) == 1


def test_refresh_in_progress_matches_skips_matches_already_full_time(db_conn):
    kickoff = datetime.now(timezone.utc) - timedelta(hours=2)
    _seed_match_intelligence_row(db_conn, "FULL_TIME", kickoff)
    result = refresh_in_progress_matches(db_conn)
    assert result == {"refreshed": 0, "skipped": 0, "failed": 0}


def test_refresh_in_progress_matches_skips_matches_outside_the_bounded_window(db_conn):
    old_kickoff = datetime.now(timezone.utc) - timedelta(hours=30)
    _seed_match_intelligence_row(db_conn, "PRE_MATCH", old_kickoff)
    result = refresh_in_progress_matches(db_conn)
    assert result["refreshed"] == 0
    assert result["skipped"] == 1


def test_refresh_in_progress_matches_counts_failures_without_raising(monkeypatch, db_conn):
    kickoff = datetime.now(timezone.utc) - timedelta(hours=1)
    _seed_match_intelligence_row(db_conn, "LIVE", kickoff)

    def boom(conn, home, away, day):
        raise FotMobFetchError("simulated failure")

    monkeypatch.setattr(fotmob_mod, "sync_match", boom)

    result = refresh_in_progress_matches(db_conn)
    assert result["failed"] == 1
    assert result["refreshed"] == 0
