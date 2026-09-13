from click.testing import CliRunner

from fpl_agent.cli.main import cli


def test_sync_live_odds_reports_result(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod
    monkeypatch.setattr(
        main_mod, "sync_api_football_odds",
        lambda conn, force=False: {"skipped": False, "matched": 8, "unmatched": 2, "failed": 0, "dates_queried": 2},
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-live-odds"])

    assert result.exit_code == 0, result.output
    assert "matched          8" in result.output


def test_sync_live_odds_reports_a_skipped_run_cleanly(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod
    monkeypatch.setattr(
        main_mod, "sync_api_football_odds",
        lambda conn, force=False: {"skipped": True, "reason": "fresh (10min old, cadence 240min)"},
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-live-odds"])

    assert result.exit_code == 0, result.output
    assert "fresh" in result.output


def test_sync_live_odds_reports_missing_key_cleanly(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod
    from fpl_agent.ingestion.api_football_odds_source import ApiFootballOddsFetchError

    def raise_no_key(conn, force=False):
        raise ApiFootballOddsFetchError("API_FOOTBALL_KEY not set - see .env.example for how to configure a free api-football.com key")

    monkeypatch.setattr(main_mod, "sync_api_football_odds", raise_no_key)

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-live-odds"])

    assert result.exit_code == 1
    assert "API_FOOTBALL_KEY not set" in result.output
