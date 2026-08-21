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
