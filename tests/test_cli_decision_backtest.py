from click.testing import CliRunner

from fpl_agent.cli.main import cli

from test_decision_calibration import _seed_actual_points, _seed_players, _ta_transfer
from fpl_agent.models.decision_calibration import record_decision_snapshot, reveal_decision_outcomes


def test_decision_backtest_cmd_reports_no_data_yet(db_conn):
    result = CliRunner().invoke(cli, ["decision-backtest"])
    assert result.exit_code == 0
    assert "no real decision-outcome rows revealed yet" in result.output


def test_decision_backtest_cmd_reports_a_real_revealed_row(db_conn):
    _seed_players(db_conn, [1, 2, 3, 4])
    record_decision_snapshot(db_conn, event=2, ta=_ta_transfer(out_id=1, in_id=2, alt_out=3, alt_in=4), ca=None)
    _seed_actual_points(db_conn, 1, 2, 2)
    _seed_actual_points(db_conn, 2, 2, 10)
    _seed_actual_points(db_conn, 3, 2, 5)
    _seed_actual_points(db_conn, 4, 2, 6)
    reveal_decision_outcomes(db_conn, event=2)

    result = CliRunner().invoke(cli, ["decision-backtest"])
    assert result.exit_code == 0, result.output
    assert "transfer" in result.output
    assert "n=1" in result.output  # too few samples for significance, must say so
    assert "GW2" in result.output
