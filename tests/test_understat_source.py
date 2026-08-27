import json

from fpl_agent.ingestion.understat_source import (
    backfill_understat, parse_understat_match_players, repair_unresolved_player_ids,
)


def test_parse_understat_match_players_flattens_both_sides():
    rosters = {
        "h": {"101": {"id": "101", "player": "Erling Haaland", "team_id": "50",
                       "time": "90", "goals": "2", "assists": "0", "shots": "5", "xG": "1.8",
                       "xA": "0.1", "key_passes": "1", "yellow_card": "0", "red_card": "0"}},
        "a": {"202": {"id": "202", "player": "Cole Palmer", "team_id": "8",
                       "time": "90", "goals": "0", "assists": "1", "shots": "2", "xG": "0.3",
                       "xA": "0.5", "key_passes": "3", "yellow_card": "1", "red_card": "0"}},
    }
    team_names = {"50": "Man City", "8": "Chelsea"}
    rows = parse_understat_match_players(rosters, match_id="12345", match_date="2024-08-17", season="2024-25",
                                          team_names=team_names)
    assert len(rows) == 2
    haaland = next(r for r in rows if r["understat_player_id"] == "101")
    assert haaland["player_name"] == "Erling Haaland"
    assert haaland["team_name"] == "Man City"  # resolved from team_id via the teams map, not a "team" field
    assert haaland["goals"] == 2
    assert haaland["xg"] == 1.8
    assert haaland["minutes"] == 90  # sourced from the real API's "time" field, not "minutes"


def test_parse_understat_match_players_raises_for_unknown_team_id():
    rosters = {"h": {"101": {"id": "101", "player": "X", "team_id": "999", "time": "90", "goals": "0",
                              "assists": "0", "shots": "0", "xG": "0", "xA": "0", "key_passes": "0",
                              "yellow_card": "0", "red_card": "0"}}, "a": {}}
    import pytest
    with pytest.raises(KeyError):
        parse_understat_match_players(rosters, "1", "2024-08-17", "2024-25", team_names={})


_SEASON_JSON = json.dumps({
    "teams": {"50": {"id": "50", "title": "Man City"}, "8": {"id": "8", "title": "Chelsea"}},
    "players": [],
    "dates": [{"id": "555", "isResult": True, "h": {"title": "Man City"}, "a": {"title": "Chelsea"},
               "datetime": "2024-08-17 15:00:00"}],
})

_MATCH_JSON = json.dumps({
    "rosters": {
        "h": {"101": {"id": "101", "player": "Erling Haaland", "team_id": "50", "time": "90",
                       "goals": "2", "assists": "0", "shots": "5", "xG": "1.8", "xA": "0.1",
                       "key_passes": "1", "yellow_card": "0", "red_card": "0"}},
        "a": {},
    },
    "shots": [], "tmpl": "",
})


def test_backfill_understat_upserts_player_match_stats(db_conn):
    summary = backfill_understat(
        db_conn, "2024-25",
        season_page_html=_SEASON_JSON,
        match_pages={"555": _MATCH_JSON},
    )
    assert summary["matches_processed"] == 1
    assert summary["player_rows_inserted"] == 1
    row = db_conn.execute("SELECT * FROM player_match_stats_history").fetchone()
    assert row["goals"] == 2
    assert row["xg"] == 1.8
    assert row["player_id"] is None  # no players seeded in this test -> unresolved, not fabricated


def test_backfill_understat_skips_already_backfilled_matches_on_a_second_call(db_conn):
    """Real gap found 2026-08-26: this function had no idempotency at all -
    every call re-fetched every played match's Understat page again, unsafe
    to ever wire into a regular automatic cycle (a monotonically growing
    re-fetch every ~30min as a season progresses). A second call with the
    same match already present must not even attempt to fetch it again -
    proven here by NOT providing match_pages for the already-backfilled
    match id on the second call (a real fetch attempt with no page supplied
    would return None and be silently skipped either way, so match_pages={}
    combined with matches_processed==0 is the real proof it never entered
    the fetch path a second time)."""
    backfill_understat(db_conn, "2024-25", season_page_html=_SEASON_JSON, match_pages={"555": _MATCH_JSON})

    summary = backfill_understat(db_conn, "2024-25", season_page_html=_SEASON_JSON, match_pages={})

    assert summary["matches_processed"] == 0
    assert summary["player_rows_inserted"] == 0
    row = db_conn.execute("SELECT COUNT(*) AS n FROM player_match_stats_history").fetchone()
    assert row["n"] == 1  # unchanged, no duplicate row either


def test_backfill_understat_skips_unplayed_fixtures(db_conn):
    season_json = json.dumps({
        "teams": {"50": {"id": "50", "title": "Man City"}, "8": {"id": "8", "title": "Chelsea"}},
        "players": [],
        "dates": [
            {"id": "555", "isResult": True, "h": {"title": "Man City"}, "a": {"title": "Chelsea"},
             "datetime": "2024-08-17 15:00:00"},
            {"id": "556", "isResult": False, "h": {"title": "Arsenal"}, "a": {"title": "Fulham"},
             "datetime": "2026-08-30 15:00:00"},
        ],
    })
    summary = backfill_understat(
        db_conn, "2024-25",
        season_page_html=season_json,
        match_pages={"555": _MATCH_JSON},
    )
    assert summary["matches_processed"] == 1  # the unplayed fixture (556) is never even requested


def test_backfill_understat_raises_on_malformed_league_json(db_conn):
    from fpl_agent.ingestion.understat_source import UnderstatParseError
    import pytest
    with pytest.raises(UnderstatParseError):
        backfill_understat(db_conn, "2024-25", season_page_html="not valid json")


def test_backfill_understat_raises_when_dates_key_missing(db_conn):
    import pytest
    with pytest.raises(KeyError):
        backfill_understat(db_conn, "2024-25", season_page_html=json.dumps({"teams": {}, "players": []}))


# --- repair_unresolved_player_ids (2026-08-28, real Understat re-resolution
# pass) ---

def _seed_haaland_player(conn, team_id=50, fpl_team_id=1):
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','t0')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'t0')",
        (fpl_team_id, 100 + fpl_team_id, "Man City", "MCI"),
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, first_name, second_name, team_id, element_type, status, updated_at) "
        "VALUES (999,999,'Haaland','Erling','Haaland',?,1,'a','t0')",
        (fpl_team_id,),
    )
    conn.commit()


def test_repair_unresolved_player_ids_resolves_a_real_row(db_conn, monkeypatch):
    import fpl_agent.ingestion.understat_source as us_mod

    # Seed one real unresolved row (no players in the DB at backfill time).
    backfill_understat(db_conn, "2024-25", season_page_html=_SEASON_JSON, match_pages={"555": _MATCH_JSON})
    row = db_conn.execute("SELECT id, player_id FROM player_match_stats_history WHERE understat_player_id='101'").fetchone()
    assert row["player_id"] is None

    # NOW seed the real player (as if a later live sync added them) and re-fetch the same match.
    _seed_haaland_player(db_conn)
    monkeypatch.setattr(us_mod, "fetch_understat_match_page", lambda match_id: _MATCH_JSON)

    result = repair_unresolved_player_ids(db_conn, delay=0.0)

    assert result == {"matches_processed": 1, "rows_resolved": 1, "rows_still_unresolved": 0, "errors": 0}
    fixed = db_conn.execute("SELECT player_id FROM player_match_stats_history WHERE id=?", (row["id"],)).fetchone()
    assert fixed["player_id"] == 999


def test_repair_unresolved_player_ids_never_fabricates_when_the_real_player_still_cant_be_found(db_conn, monkeypatch):
    import fpl_agent.ingestion.understat_source as us_mod

    backfill_understat(db_conn, "2024-25", season_page_html=_SEASON_JSON, match_pages={"555": _MATCH_JSON})
    # No player seeded at all this time - a genuinely unresolvable real row.
    monkeypatch.setattr(us_mod, "fetch_understat_match_page", lambda match_id: _MATCH_JSON)

    result = repair_unresolved_player_ids(db_conn, delay=0.0)

    assert result["rows_resolved"] == 0
    assert result["rows_still_unresolved"] == 1
    row = db_conn.execute("SELECT player_id FROM player_match_stats_history").fetchone()
    assert row["player_id"] is None


def test_repair_unresolved_player_ids_never_creates_a_duplicate_row(db_conn, monkeypatch):
    import fpl_agent.ingestion.understat_source as us_mod

    backfill_understat(db_conn, "2024-25", season_page_html=_SEASON_JSON, match_pages={"555": _MATCH_JSON})
    _seed_haaland_player(db_conn)
    monkeypatch.setattr(us_mod, "fetch_understat_match_page", lambda match_id: _MATCH_JSON)

    repair_unresolved_player_ids(db_conn, delay=0.0)

    count = db_conn.execute("SELECT COUNT(*) n FROM player_match_stats_history").fetchone()["n"]
    assert count == 1  # updated in place, never a second row


def test_repair_unresolved_player_ids_respects_the_season_filter(db_conn, monkeypatch):
    import fpl_agent.ingestion.understat_source as us_mod

    backfill_understat(db_conn, "2024-25", season_page_html=_SEASON_JSON, match_pages={"555": _MATCH_JSON})
    _seed_haaland_player(db_conn)
    monkeypatch.setattr(us_mod, "fetch_understat_match_page", lambda match_id: _MATCH_JSON)

    result = repair_unresolved_player_ids(db_conn, season="2099-00", delay=0.0)  # a season with no real unresolved rows

    assert result == {"matches_processed": 0, "rows_resolved": 0, "rows_still_unresolved": 0, "errors": 0}


def test_repair_unresolved_player_ids_counts_a_real_fetch_error_without_crashing(db_conn, monkeypatch):
    import fpl_agent.ingestion.understat_source as us_mod
    from fpl_agent.ingestion.understat_source import UnderstatFetchError

    backfill_understat(db_conn, "2024-25", season_page_html=_SEASON_JSON, match_pages={"555": _MATCH_JSON})

    def _boom(match_id):
        raise UnderstatFetchError("real network failure")

    monkeypatch.setattr(us_mod, "fetch_understat_match_page", _boom)

    result = repair_unresolved_player_ids(db_conn, delay=0.0)

    assert result["errors"] == 1
    assert result["matches_processed"] == 0
