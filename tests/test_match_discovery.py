from datetime import datetime, timedelta, timezone

import fpl_agent.ingestion.fotmob_source as fotmob_mod
from fpl_agent.ingestion.fotmob_source import FotMobFetchError
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.models.match_discovery import discover_and_register_matches
from fpl_agent.normalization.fpl_core import (
    normalize_element_types,
    normalize_events,
    normalize_players,
    normalize_teams,
)

from test_fotmob_source import _DETAILS_PAYLOAD
from test_sync import make_bootstrap


def _seed_fixture(conn, kickoff: datetime, fixture_id: int = 1) -> None:
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
        "VALUES (?,?,1,?,1,2,0,0,'2026-08-20T00:00:00Z')",
        (fixture_id, 1000 + fixture_id, kickoff.isoformat().replace("+00:00", "Z")),
    )
    conn.commit()


def _stub(monkeypatch, payload=_DETAILS_PAYLOAD):
    monkeypatch.setattr(fotmob_mod, "find_match", lambda day, h, a: "5795363")
    monkeypatch.setattr(fotmob_mod, "fetch_match_details", lambda mid: payload)
    monkeypatch.setattr(fotmob_mod, "save_raw", lambda name, data: "raw/path.json")


def test_discovers_and_registers_a_new_upcoming_fixture(db_conn, monkeypatch):
    kickoff = datetime.now(timezone.utc) + timedelta(hours=2)
    _seed_fixture(db_conn, kickoff)
    _stub(monkeypatch)

    result = discover_and_register_matches(db_conn)

    assert result == {"registered": 1, "skipped": 0, "failed": 0}
    row = db_conn.execute("SELECT status FROM match_intelligence WHERE fotmob_match_id='5795363'").fetchone()
    assert row["status"] == "PRE_MATCH"


def test_skips_a_fixture_already_registered(db_conn, monkeypatch):
    kickoff = datetime.now(timezone.utc) + timedelta(hours=2)
    _seed_fixture(db_conn, kickoff)
    db_conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, source, retrieved_at, confidence) "
        "VALUES ('5795363','Premier League',?,1,2,'PRE_MATCH','fotmob','2026-08-20T00:00:00+00:00','high')",
        (kickoff.isoformat(),),
    )
    db_conn.commit()
    _stub(monkeypatch)

    result = discover_and_register_matches(db_conn)

    assert result == {"registered": 0, "skipped": 1, "failed": 0}


def test_skips_a_fixture_outside_the_discovery_window(db_conn, monkeypatch):
    kickoff = datetime.now(timezone.utc) + timedelta(days=5)  # well past the lookahead window
    _seed_fixture(db_conn, kickoff)
    _stub(monkeypatch)

    result = discover_and_register_matches(db_conn)

    assert result == {"registered": 0, "skipped": 0, "failed": 0}


def test_a_fotmob_failure_is_counted_not_raised(db_conn, monkeypatch):
    kickoff = datetime.now(timezone.utc) + timedelta(hours=2)
    _seed_fixture(db_conn, kickoff)

    def boom(day, h, a):
        raise FotMobFetchError("simulated 503")

    monkeypatch.setattr(fotmob_mod, "find_match", boom)

    result = discover_and_register_matches(db_conn)

    assert result == {"registered": 0, "skipped": 0, "failed": 1}


def test_catch_up_registers_a_played_fixture_outside_the_rolling_window(db_conn, monkeypatch):
    """Brentford 3-0 Chelsea (2026-09-18) kicked off while the daemon was
    down and never re-entered the +/-hours window: no row, no job, no
    analysis for 25 days. A played fixture in the last two weeks with no row
    is registered regardless of the window."""
    kickoff = datetime.now(timezone.utc) - timedelta(days=3)
    _seed_fixture(db_conn, kickoff)
    db_conn.execute("UPDATE fixtures SET started = 1, team_h_score = 2, team_a_score = 1, finished = 1")
    db_conn.commit()
    _stub(monkeypatch)

    result = discover_and_register_matches(db_conn)

    assert result == {"registered": 1, "skipped": 0, "failed": 0}


def test_catch_up_ignores_a_past_fixture_that_was_never_played(db_conn, monkeypatch):
    """A postponed fixture has a past kickoff and no score; retrying it
    against FotMob every cycle would just fail every cycle."""
    kickoff = datetime.now(timezone.utc) - timedelta(days=3)
    _seed_fixture(db_conn, kickoff)
    _stub(monkeypatch)

    result = discover_and_register_matches(db_conn)

    assert result == {"registered": 0, "skipped": 0, "failed": 0}


def _seed_full_time_match(conn, null_minutes: int, kickoff: datetime):
    conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, source, retrieved_at, confidence) "
        "VALUES ('5795363','Premier League',?,1,2,'FULL_TIME','fotmob','2026-08-20T00:00:00+00:00','high')",
        (kickoff.isoformat(),),
    )
    mid = conn.execute("SELECT id FROM match_intelligence").fetchone()["id"]
    for i in range(11):
        conn.execute(
            "INSERT INTO player_match_state (match_id, fotmob_player_id, team_id, started, minutes, source, retrieved_at, confidence) "
            "VALUES (?,?,1,1,?, 'fotmob','t0','high')",
            (mid, f"p{i}", None if i < null_minutes else 90),
        )
    conn.commit()


def test_resync_refetches_a_full_time_match_whose_starters_have_no_minutes(db_conn, monkeypatch):
    import fpl_agent.models.match_discovery as md

    _seed_fixture(db_conn, datetime.now(timezone.utc) - timedelta(days=2))
    _seed_full_time_match(db_conn, null_minutes=11, kickoff=datetime.now(timezone.utc) - timedelta(days=2))
    calls = []
    monkeypatch.setattr(md, "sync_match", lambda conn, h, a, d: calls.append((h, a, d)))

    result = md.resync_unsettled_full_time_matches(db_conn)

    assert result == {"refreshed": 1, "failed": 0}
    assert len(calls) == 1


def test_resync_leaves_a_match_whose_minutes_have_arrived(db_conn, monkeypatch):
    import fpl_agent.models.match_discovery as md

    _seed_fixture(db_conn, datetime.now(timezone.utc) - timedelta(days=2))
    _seed_full_time_match(db_conn, null_minutes=2, kickoff=datetime.now(timezone.utc) - timedelta(days=2))
    monkeypatch.setattr(md, "sync_match", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not refetch")))

    assert md.resync_unsettled_full_time_matches(db_conn) == {"refreshed": 0, "failed": 0}
