from click.testing import CliRunner

from fpl_agent.cli.main import cli


def test_team_news_prints_matched_articles(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(
        main_mod, "list_recent_news",
        lambda conn, limit: [{
            "id": 1, "title": "Haaland scores hat-trick", "link": "https://example.com/a1",
            "source_tier": "strong_reporter", "published_at": "2026-08-19T19:04:37+00:00",
            "players": "Haaland", "teams": "MCI",
        }],
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["team-news"])

    assert result.exit_code == 0, result.output
    assert "Haaland scores hat-trick" in result.output
    assert "players=Haaland" in result.output


def test_team_news_handles_no_data_yet(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod
    monkeypatch.setattr(main_mod, "list_recent_news", lambda conn, limit: [])

    runner = CliRunner()
    result = runner.invoke(cli, ["team-news"])

    assert result.exit_code == 0
    assert "run `fpl sync-news` first" in result.output
