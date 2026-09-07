from click.testing import CliRunner

from fpl_agent.cli.main import cli

from test_optimization_captaincy import _patch, _seed


def test_decision_fusion_cmd_reports_model_wins_by_default(db_conn, monkeypatch):
    _seed(db_conn)
    _patch(monkeypatch)

    result = CliRunner().invoke(cli, ["decision-fusion", "--squad", "1,2,3"])

    assert result.exit_code == 0, result.output
    assert "Model:       Best" in result.output
    assert "Verdict:     MODEL_WINS" in result.output
