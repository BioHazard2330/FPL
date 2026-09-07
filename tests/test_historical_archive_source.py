"""Real regression tests for the free-archive historical recovery ingestion
(2026-09-07, Phase 7.5 Parts 3/4/5/7). Never makes a real network call - the
module's own `_fetch_csv`/`_fetch_csv_optional`/`_latest_commit_sha` are
monkeypatched directly, the same pattern `test_understat_source.py` already
established for this project's other network-bound ingestion modules."""
from fpl_agent.ingestion import historical_archive_source as has_mod

_SEASON = "2023-24"

_PLAYERS_RAW = [
    {"id": "1", "code": "1001", "team": "1", "element_type": "3",
     "web_name": "TestMid", "first_name": "Test", "second_name": "Midfielder"},
    {"id": "2", "code": "1002", "team": "2", "element_type": "4",
     "web_name": "TestFwd", "first_name": "Test", "second_name": "Forward"},
]
_TEAMS = [
    {"id": "1", "name": "Team One", "short_name": "TM1", "strength_overall_home": "1200",
     "strength_overall_away": "1180", "strength_attack_home": "1150", "strength_attack_away": "1140",
     "strength_defence_home": "1160", "strength_defence_away": "1170"},
    {"id": "2", "name": "Team Two", "short_name": "TM2", "strength_overall_home": "1000",
     "strength_overall_away": "990", "strength_attack_home": "980", "strength_attack_away": "970",
     "strength_defence_home": "960", "strength_defence_away": "950"},
]
_MERGED_GW = [
    {"element": "1", "GW": "1", "value": "75", "selected": "50000", "transfers_in": "1000",
     "transfers_out": "500", "team": "Team One"},
    {"element": "2", "GW": "1", "value": "60", "selected": "20000", "transfers_in": "200",
     "transfers_out": "100", "team": "Team Two"},
    # A real, disclosed edge case: an element with no matching roster row this
    # season (should never happen within one real archive season/source, but
    # must be skipped and counted, never crash the whole ingestion).
    {"element": "999", "GW": "1", "value": "45", "selected": "10", "transfers_in": "0",
     "transfers_out": "0", "team": "Unknown"},
]
_ID_DICT = [
    {" Understat_ID": "500", " FPL_ID": "1", " Understat_Name": "Test Midfielder", " FPL_Name": "TestMid"},
]


def _patch_fetch(monkeypatch, players_raw=_PLAYERS_RAW, teams=_TEAMS, merged_gw=_MERGED_GW, id_dict=_ID_DICT):
    def fake_fetch_csv(path):
        if path.endswith("players_raw.csv"):
            return players_raw
        if path.endswith("teams.csv"):
            return teams
        if path.endswith("merged_gw.csv"):
            return merged_gw
        raise AssertionError(f"unexpected required-csv path in test: {path}")

    def fake_fetch_csv_optional(path):
        if path.endswith("id_dict.csv"):
            return id_dict
        raise AssertionError(f"unexpected optional-csv path in test: {path}")

    monkeypatch.setattr(has_mod, "_fetch_csv", fake_fetch_csv)
    monkeypatch.setattr(has_mod, "_fetch_csv_optional", fake_fetch_csv_optional)
    monkeypatch.setattr(has_mod, "_latest_commit_sha", lambda season: "test_sha_123")


def test_fetch_historical_player_roster_upserts_roster_and_team_strength(db_conn, monkeypatch):
    _patch_fetch(monkeypatch)

    element_to_code = has_mod.fetch_historical_player_roster(db_conn, _SEASON, "test_sha_123")

    assert element_to_code == {"1": "1001", "2": "1002"}
    roster = db_conn.execute(
        "SELECT * FROM historical_player_roster WHERE season=? ORDER BY player_code", (_SEASON,),
    ).fetchall()
    assert len(roster) == 2
    assert roster[0]["player_code"] == 1001
    assert roster[0]["team_short_name"] == "TM1"
    assert roster[0]["position"] == "MID"

    strength = db_conn.execute(
        "SELECT * FROM historical_team_strength WHERE season=? ORDER BY team_short_name", (_SEASON,),
    ).fetchall()
    assert len(strength) == 2
    assert strength[0]["strength_overall_home"] == 1200


def test_fetch_historical_gw_snapshot_resolves_code_and_skips_unmapped_elements(db_conn, monkeypatch):
    _patch_fetch(monkeypatch)
    element_to_code = has_mod.fetch_historical_player_roster(db_conn, _SEASON, "test_sha_123")

    n = has_mod.fetch_historical_gw_snapshot(db_conn, _SEASON, element_to_code, "test_sha_123")

    assert n == 2  # the real, unmapped element=999 row is skipped, not inserted
    rows = db_conn.execute(
        "SELECT * FROM historical_gw_snapshot WHERE season=? ORDER BY player_code", (_SEASON,),
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["player_code"] == 1001
    assert rows[0]["price_tenths"] == 75
    assert rows[0]["selected_count"] == 50000

    lineage = db_conn.execute(
        "SELECT * FROM historical_data_lineage WHERE season=? AND field='gw_snapshot'", (_SEASON,),
    ).fetchone()
    assert lineage["row_count"] == 2
    assert "1 rows skipped" in lineage["transformation"]
    assert lineage["confidence"] == "PARTIAL"


def test_fetch_historical_identity_crosswalk_normalizes_leading_space_headers(db_conn, monkeypatch):
    _patch_fetch(monkeypatch)
    element_to_code = has_mod.fetch_historical_player_roster(db_conn, _SEASON, "test_sha_123")

    n = has_mod.fetch_historical_identity_crosswalk(db_conn, _SEASON, element_to_code, "test_sha_123")

    assert n == 1
    row = db_conn.execute(
        "SELECT * FROM historical_identity_crosswalk WHERE season=?", (_SEASON,),
    ).fetchone()
    assert row["understat_player_id"] == "500"
    assert row["player_code"] == 1001


def test_fetch_historical_identity_crosswalk_discloses_a_real_missing_file_without_crashing(db_conn, monkeypatch):
    """Real, confirmed archive limitation: id_dict.csv only exists for
    2021-22/2022-23. A later season must return 0 rows and a disclosed
    PARTIAL lineage note, never raise."""
    _patch_fetch(monkeypatch, id_dict=None)
    element_to_code = has_mod.fetch_historical_player_roster(db_conn, _SEASON, "test_sha_123")

    n = has_mod.fetch_historical_identity_crosswalk(db_conn, _SEASON, element_to_code, "test_sha_123")

    assert n == 0
    lineage = db_conn.execute(
        "SELECT * FROM historical_data_lineage WHERE season=? AND field='identity_crosswalk'", (_SEASON,),
    ).fetchone()
    assert lineage["confidence"] == "PARTIAL"
    assert lineage["row_count"] == 0
    assert "does not exist" in lineage["transformation"]


def test_fetch_historical_season_is_idempotent(db_conn, monkeypatch):
    """Real, required property for a safe re-run - upserting the same real
    season twice must not create duplicate rows."""
    _patch_fetch(monkeypatch)

    result1 = has_mod.fetch_historical_season(db_conn, _SEASON)
    result2 = has_mod.fetch_historical_season(db_conn, _SEASON)

    assert result1 == result2
    assert db_conn.execute(
        "SELECT COUNT(*) FROM historical_gw_snapshot WHERE season=?", (_SEASON,),
    ).fetchone()[0] == 2
    assert db_conn.execute(
        "SELECT COUNT(*) FROM historical_player_roster WHERE season=?", (_SEASON,),
    ).fetchone()[0] == 2


def test_resolve_via_archive_crosswalk_finds_a_real_mapped_player(db_conn, monkeypatch):
    _patch_fetch(monkeypatch)
    has_mod.fetch_historical_player_roster(db_conn, _SEASON, "test_sha_123")
    has_mod.fetch_historical_identity_crosswalk(db_conn, _SEASON, {"1": "1001", "2": "1002"}, "test_sha_123")
    db_conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1, 1, 'Team A', 'TMA', 't0')")
    db_conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (3, 'Midfielder', 'MID', 'Midfielders', 't0')"
    )
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (77, 1001, 'TestMid', 1, 3, 'a', 't0')"
    )
    db_conn.commit()

    assert has_mod.resolve_via_archive_crosswalk(db_conn, "500", _SEASON) == 77


def test_resolve_via_archive_crosswalk_returns_none_for_an_unmapped_id(db_conn):
    assert has_mod.resolve_via_archive_crosswalk(db_conn, "999999", "2099-00") is None


def test_fetch_historical_season_returns_a_real_summary(db_conn, monkeypatch):
    _patch_fetch(monkeypatch)

    result = has_mod.fetch_historical_season(db_conn, _SEASON)

    assert result["season"] == _SEASON
    assert result["commit_sha"] == "test_sha_123"
    assert result["roster_rows"] == 2
    assert result["gw_snapshot_rows"] == 2
    assert result["identity_crosswalk_rows"] == 1
