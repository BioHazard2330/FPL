from click.testing import CliRunner

from fpl_agent.cli.main import cli


def test_repair_understat_players_cmd_reports_zero_when_nothing_unresolved(db_conn):
    result = CliRunner().invoke(cli, ["repair-understat-players", "--season", "2025-26"])
    assert result.exit_code == 0, result.output
    assert "matches processed      0" in result.output
