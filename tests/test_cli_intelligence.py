from click.testing import CliRunner

from fpl_agent.cli.main import cli

from test_manager_intelligence import _seed_match as _seed_manager_match
from test_player_intelligence import _seed_player, _seed_qualitative_state
from test_qualitative_trends import _seed_match, _seed_observation


def test_player_intelligence_cmd_reports_no_analysis(db_conn):
    _seed_player(db_conn, 1)

    result = CliRunner().invoke(cli, ["player-intelligence", "1"])

    assert result.exit_code == 0, result.output
    assert "no qualitative analysis recorded yet" in result.output


def test_player_intelligence_cmd_reports_unknown_player(db_conn):
    result = CliRunner().invoke(cli, ["player-intelligence", "99999"])

    assert result.exit_code == 1
    assert "unknown player_id" in result.output


def test_player_intelligence_cmd_shows_current_state_and_trend(db_conn):
    _seed_player(db_conn, 1)
    _seed_match(db_conn, 1, "m1", "2026-08-01T15:00:00Z")
    _seed_observation(db_conn, 1, "player", 1, "ROLE", "POSITIVE")
    _seed_qualitative_state(db_conn, 1, match_id=1)

    result = CliRunner().invoke(cli, ["player-intelligence", "1"])

    assert result.exit_code == 0, result.output
    assert "starting striker" in result.output
    assert "NEW_SIGNAL" in result.output


def test_manager_intelligence_cmd_reports_insufficient_history(db_conn):
    db_conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Team A','TMA','t0')"
    )
    db_conn.commit()

    result = CliRunner().invoke(cli, ["manager-intelligence", "1"])

    assert result.exit_code == 0, result.output
    assert "need at least" in result.output.lower()


def test_manager_intelligence_cmd_shows_real_pattern(db_conn):
    _seed_manager_match(db_conn, 1, "m1", "2026-08-01T15:00:00Z", team_id=1, formation="4-3-3",
                         starters=[1, 2, 3], sub_off_minutes={1: 70})
    _seed_manager_match(db_conn, 2, "m2", "2026-08-08T15:00:00Z", team_id=1, formation="4-3-3",
                         starters=[1, 2, 4], sub_off_minutes={2: 60})

    result = CliRunner().invoke(cli, ["manager-intelligence", "1"])

    assert result.exit_code == 0, result.output
    assert "4-3-3" in result.output
    assert "0.5" in result.output
