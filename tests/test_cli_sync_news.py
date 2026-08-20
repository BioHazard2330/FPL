from click.testing import CliRunner

from fpl_agent.cli.main import cli


def test_sync_news_reports_result(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(
        main_mod, "sync_all_news_sources",
        lambda conn, limit: {"fetched": 12, "new_items": 3, "players_linked": 2, "teams_linked": 1, "errors": {}},
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-news"])

    assert result.exit_code == 0, result.output
    assert "new items       3" in result.output
    assert "players linked  2" in result.output


def test_sync_news_reports_partial_source_failure_but_still_succeeds(monkeypatch, db_conn):
    """One source failing (e.g. Sky Sports RSS temporarily down) must not
    abort the whole sync when the other source succeeded - a real per-source
    failure is a warning, not a hard error, as long as something was fetched."""
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(
        main_mod, "sync_all_news_sources",
        lambda conn, limit: {
            "fetched": 10, "new_items": 2, "players_linked": 1, "teams_linked": 1,
            "errors": {"sky_sports_rss": "failed to fetch https://example.com: timeout"},
        },
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-news"])

    assert result.exit_code == 0, result.output
    assert "WARNING: sky_sports_rss failed" in result.output


def test_sync_news_fails_when_every_source_fails(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(
        main_mod, "sync_all_news_sources",
        lambda conn, limit: {
            "fetched": 0, "new_items": 0, "players_linked": 0, "teams_linked": 0,
            "errors": {
                "bbc_sport_rss": "failed to fetch https://example.com: timeout",
                "sky_sports_rss": "failed to fetch https://example.com: timeout",
            },
        },
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-news"])

    assert result.exit_code == 1
