import pytest
from click.testing import CliRunner

import fpl_agent.cli.main as main_mod
from fpl_agent.cli.main import cli


@pytest.fixture(autouse=True)
def _isolated_dashboard_write(tmp_path, monkeypatch):
    """Real, confirmed production bug (2026-09-02) - THE exact, byte-for-byte
    confirmed source of a real live incident: the real `data/dashboard.html`
    was found overwritten with this file's own fixture content verbatim
    ("Real full-time headline", "won at home", "Coventry City"/"COV", GW1,
    NO SQUAD) after a full test-suite run. `test_match_report_cmd_prints_
    qualitative_analysis_and_user_observations` invokes the real `match-
    analyze` CLI command (`cli/main.py::match_analyze_cmd`), which calls the
    real `_write_dashboard()` whenever `change_events_written > 0` - this
    file never isolated `DATA_DIR` the way `test_cli_live_match_poll.py`'s
    own `_isolated_live_poll_lock` fixture already does for the identical
    bug class there (see that fixture's own docstring - same root cause,
    different file). The read side was already correctly isolated (`db_conn`
    patches `database.connection.DATA_DIR`/`DB_PATH`, so `_write_dashboard`'s
    own `get_connection()` read this file's own Arsenal/Coventry City
    fixture, not real production data) - only the WRITE destination was not,
    so the real dashboard got silently overwritten with fixture content on
    every full-suite run that reached this test. Every test in this file now
    gets its own per-test tmp_path instead."""
    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)


def test_sync_match_cmd_reports_result(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(
        main_mod,
        "sync_match",
        lambda conn, home, away, day: {
            "match_id": 1, "fotmob_match_id": "5795363", "status": "PRE_MATCH",
            "kickoff_utc": "2026-08-21T19:00:00.000Z", "home_team": "Arsenal", "away_team": "Coventry City",
            "players_ingested": 22, "players_resolved": 20, "team_states_ingested": 2,
        },
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-match", "Arsenal", "Coventry", "--date", "2026-08-21"])

    assert result.exit_code == 0, result.output
    assert "fotmob match id   5795363" in result.output
    assert "status            PRE_MATCH" in result.output


def test_sync_match_cmd_reports_failure_cleanly(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod
    from fpl_agent.ingestion.fotmob_source import FotMobFetchError

    def _boom(conn, home, away, day):
        raise FotMobFetchError("no FotMob match found for 'X' vs 'Y' on 2026-08-21")

    monkeypatch.setattr(main_mod, "sync_match", _boom)

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-match", "X", "Y", "--date", "2026-08-21"])

    assert result.exit_code == 1
    assert "no FotMob match found" in result.output


def test_match_report_cmd_prints_not_found_cleanly(db_conn):
    runner = CliRunner()
    result = runner.invoke(cli, ["match-report", "999999"])
    assert result.exit_code == 1
    assert "run `fpl sync-match` first" in result.output


def test_match_report_cmd_prints_real_persisted_state(db_conn):
    from fpl_agent.ingestion.sync import _upsert_many
    from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams
    from test_sync import make_bootstrap

    bootstrap = make_bootstrap()
    bootstrap["teams"].append({
        "id": 2, "code": 7, "name": "Coventry City", "short_name": "COV",
        "strength_overall_home": 2, "strength_overall_away": 2,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(db_conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(db_conn, "players", normalize_players(bootstrap), "t0")
    db_conn.commit()

    now = "2026-08-21T15:00:00+00:00"
    db_conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "home_score, away_score, source, retrieved_at, confidence) "
        "VALUES ('5795363','Premier League','2026-08-21T19:00:00.000Z',1,2,'PRE_MATCH',NULL,NULL,'fotmob',?,'high')",
        (now,),
    )
    db_conn.commit()
    match_id = db_conn.execute("SELECT id FROM match_intelligence").fetchone()["id"]
    db_conn.execute(
        "INSERT INTO player_match_state (match_id, player_id, fotmob_player_id, team_id, started, source, retrieved_at, confidence) "
        "VALUES (?, NULL, '1', 1, 1, 'fotmob', ?, 'medium')",
        (match_id, now),
    )
    db_conn.commit()

    runner = CliRunner()
    result = runner.invoke(cli, ["match-report", "5795363"])

    assert result.exit_code == 0, result.output
    assert "status=PRE_MATCH" in result.output
    assert "UNRESOLVED" in result.output
    assert "(none yet - run the match-intelligence-analysis skill)" in result.output
    assert "ANALYSIS SUMMARY (0)" in result.output
    assert "PLAYER QUALITATIVE STATE (0)" in result.output
    assert "TEAM QUALITATIVE STATE (0)" in result.output
    assert "USER OBSERVATIONS (0)" in result.output


def test_match_report_cmd_prints_qualitative_analysis_and_user_observations(tmp_path, db_conn):
    import json

    from fpl_agent.ingestion.sync import _upsert_many
    from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams
    from test_sync import make_bootstrap

    bootstrap = make_bootstrap()
    bootstrap["teams"].append({
        "id": 2, "code": 7, "name": "Coventry City", "short_name": "COV",
        "strength_overall_home": 2, "strength_overall_away": 2,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    _upsert_many(db_conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(db_conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(db_conn, "players", normalize_players(bootstrap), "t0")
    db_conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "home_score, away_score, source, retrieved_at, confidence) "
        "VALUES ('5795363','Premier League','2026-08-21T19:00:00.000Z',1,2,'FULL_TIME',2,0,"
        "'fotmob','2026-08-21T21:00:00+00:00','high')"
    )
    db_conn.commit()

    runner = CliRunner()
    payload = {
        "headline": "Real full-time headline",
        "uncertainties": "one match only",
        "observations": [
            {"subject_type": "player", "subject_id": 1, "observation_type": "ROLE",
             "observed": "started, 90 minutes", "inferred": "trusted starter", "fpl_direction": "POSITIVE",
             "fpl_signal": "MINUTES", "fpl_reason": "played full match", "confidence": "medium"},
        ],
        "player_states": [
            {"player_id": 1, "role": "starter", "tactical_signal": "steady",
             "fpl_outlook": "positive", "confidence": "medium"},
        ],
        "team_states": [
            {"team_id": 1, "tactical_signal": "steady", "key_observation": "won at home", "confidence": "medium"},
        ],
    }
    tmp_file = tmp_path / "analysis_payload_test.json"
    tmp_file.write_text(json.dumps(payload), encoding="utf-8")

    analyze_result = runner.invoke(cli, ["match-analyze", "5795363", "--phase", "full_time", "--file", str(tmp_file)])
    assert analyze_result.exit_code == 0, analyze_result.output

    note_result = runner.invoke(cli, ["match-note", "--player", "1", "--sentiment", "positive",
                                       "--note", "Looked sharp all game.", "--match", "5795363"])
    assert note_result.exit_code == 0, note_result.output

    result = runner.invoke(cli, ["match-report", "5795363"])
    assert result.exit_code == 0, result.output
    assert "Real full-time headline" in result.output
    assert "PLAYER QUALITATIVE STATE (1)" in result.output
    assert "TEAM QUALITATIVE STATE (1)" in result.output
    assert "USER OBSERVATIONS (1)" in result.output
    assert "Looked sharp all game." in result.output
