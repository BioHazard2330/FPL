import json

from click.testing import CliRunner

from fpl_agent.cli.main import cli
from fpl_agent.ingestion.sync import _upsert_many
from fpl_agent.normalization.fpl_core import normalize_element_types, normalize_players, normalize_teams

from test_sync import make_bootstrap

_PAYLOAD = {
    "headline": "Test headline",
    "uncertainties": "small sample",
    "observations": [
        {"subject_type": "player", "subject_id": 1, "observation_type": "ROLE",
         "observed": "started, 90 minutes", "inferred": "trusted starter", "fpl_direction": "POSITIVE",
         "fpl_signal": "MINUTES", "fpl_reason": "played full match", "confidence": "medium"},
    ],
}


def _seed_match(conn, status="FULL_TIME"):
    bootstrap = make_bootstrap()
    bootstrap["teams"].append({
        "id": 2, "code": 7, "name": "Coventry City", "short_name": "COV",
        "strength_overall_home": 2, "strength_overall_away": 2,
        "strength_attack_home": 0, "strength_attack_away": 0,
        "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 2,
    })
    _upsert_many(conn, "teams", normalize_teams(bootstrap), "t0")
    _upsert_many(conn, "element_types", normalize_element_types(bootstrap), "t0")
    _upsert_many(conn, "players", normalize_players(bootstrap), "t0")
    conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "home_score, away_score, source, retrieved_at, confidence) "
        "VALUES ('5795363','Premier League','2026-08-21T19:00:00.000Z',1,2,?,NULL,NULL,'fotmob','2026-08-21T15:00:00+00:00','high')",
        (status,),
    )
    conn.commit()


def test_match_analyze_cmd_persists_payload(tmp_path, db_conn):
    _seed_match(db_conn, status="FULL_TIME")
    payload_path = tmp_path / "analysis.json"
    payload_path.write_text(json.dumps(_PAYLOAD), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["match-analyze", "5795363", "--phase", "full_time", "--file", str(payload_path)])

    assert result.exit_code == 0, result.output
    assert "observations written   1" in result.output
    assert "implications written   1" in result.output


def test_match_analyze_cmd_refuses_full_time_before_finish(tmp_path, db_conn):
    _seed_match(db_conn, status="LIVE")
    payload_path = tmp_path / "analysis.json"
    payload_path.write_text(json.dumps(_PAYLOAD), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["match-analyze", "5795363", "--phase", "full_time", "--file", str(payload_path)])

    assert result.exit_code == 1
    assert "refusing FULL_TIME" in result.output


def test_match_analyze_cmd_reports_unknown_match_cleanly(tmp_path, db_conn):
    payload_path = tmp_path / "analysis.json"
    payload_path.write_text(json.dumps(_PAYLOAD), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["match-analyze", "999999", "--phase", "full_time", "--file", str(payload_path)])

    assert result.exit_code == 1
    assert "no match intelligence found" in result.output


def test_match_note_cmd_records_a_player_observation(db_conn):
    runner = CliRunner()
    result = runner.invoke(cli, ["match-note", "--player", "1", "--sentiment", "positive", "--note", "Looked sharp."])
    assert result.exit_code == 0, result.output
    assert "recorded USER_OBSERVATION" in result.output
    row = db_conn.execute("SELECT * FROM user_observations").fetchone()
    assert row["subject_type"] == "player"
    assert row["note"] == "Looked sharp."


def test_match_note_cmd_requires_exactly_one_subject(db_conn):
    runner = CliRunner()
    result = runner.invoke(cli, ["match-note", "--note", "no subject given"])
    assert result.exit_code == 1
    assert "exactly one of --player or --team" in result.output

    result2 = runner.invoke(cli, ["match-note", "--player", "1", "--team", "2", "--note", "both given"])
    assert result2.exit_code == 1
