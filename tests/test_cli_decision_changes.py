from click.testing import CliRunner

from fpl_agent.cli.main import cli
from fpl_agent.database.decisions import log_decision


def test_decision_changes_cmd_reports_none_with_no_history(db_conn):
    result = CliRunner().invoke(cli, ["decision-changes"])
    assert result.exit_code == 0
    assert "no real recommendation change" in result.output


def test_decision_changes_cmd_reports_a_real_change(db_conn):
    log_decision(db_conn, "strategic_plan", summary="a", detail={"current_recommendation": {"label": "ROLL", "verdict": "ACT"}})
    log_decision(db_conn, "strategic_plan", summary="b", detail={"current_recommendation": {"label": "PLAY WILDCARD", "verdict": "ACT"}})

    result = CliRunner().invoke(cli, ["decision-changes"])

    assert result.exit_code == 0, result.output
    assert "ROLL" in result.output
    assert "PLAY WILDCARD" in result.output
