from click.testing import CliRunner

from fpl_agent.cli.main import cli


def test_backtest_bonus_flag_reports_result(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod
    from fpl_agent.backtesting.harness import BacktestResult, BonusRegressionBacktestResult

    monkeypatch.setattr(
        main_mod, "run_backtest",
        lambda conn, season, model_version: BacktestResult(
            model_version=model_version, season=season, rounds_evaluated=1, predictions_scored=1,
            mae=1.0, rmse=1.0, baseline_mae=1.0,
        ),
    )
    monkeypatch.setattr(main_mod, "save_backtest_run", lambda conn, result: 1)
    monkeypatch.setattr(
        main_mod, "score_bonus_regression",
        lambda conn: BonusRegressionBacktestResult(
            players_evaluated=10, shrunk_mae=0.5, naive_mae=0.8, shrunk_win_rate=0.7, insufficient_data=False,
        ),
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["backtest", "--season", "2024-25", "--bonus"])

    assert result.exit_code == 0, result.output
    assert "bonus regression" in result.output
    assert "0.5" in result.output
    assert "0.8" in result.output
