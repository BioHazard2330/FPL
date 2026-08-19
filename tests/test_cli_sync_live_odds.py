from click.testing import CliRunner

from fpl_agent.cli.main import cli


def test_sync_live_odds_reports_result(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod
    monkeypatch.setattr(main_mod, "sync_live_odds", lambda conn: {"fetched": 10, "matched": 8, "unmatched": 2})

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-live-odds"])

    assert result.exit_code == 0, result.output
    assert "matched          8" in result.output


def test_sync_live_odds_reports_missing_key_cleanly(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod
    from fpl_agent.ingestion.odds_live_source import OddsLiveFetchError

    def raise_no_key(conn):
        raise OddsLiveFetchError("ODDS_API_KEY not set - see .env.example for how to configure a free the-odds-api.com key")

    monkeypatch.setattr(main_mod, "sync_live_odds", raise_no_key)

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-live-odds"])

    assert result.exit_code == 1
    assert "ODDS_API_KEY not set" in result.output
