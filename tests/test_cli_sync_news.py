from click.testing import CliRunner

from fpl_agent.cli.main import cli


def test_sync_news_reports_result(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(
        main_mod, "sync_news",
        lambda conn, limit: {"fetched": 12, "new_items": 3, "players_linked": 2, "teams_linked": 1},
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-news"])

    assert result.exit_code == 0, result.output
    assert "new items       3" in result.output
    assert "players linked  2" in result.output


def test_sync_news_reports_fetch_error_cleanly(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod
    from fpl_agent.ingestion.news_source import NewsFetchError

    def raise_fetch_error(conn, limit):
        raise NewsFetchError("failed to fetch https://example.com: timeout")

    monkeypatch.setattr(main_mod, "sync_news", raise_fetch_error)

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-news"])

    assert result.exit_code == 1
    assert "sync-news failed" in result.output
