from click.testing import CliRunner

from fpl_agent.cli.main import cli


def test_backfill_odds_season_code_conversion(monkeypatch):
    captured = {}

    def fake_backfill(conn, season, csv_text=None):
        captured["season"] = season
        return {"matches_inserted": 0, "odds_inserted": 0}

    monkeypatch.setattr("fpl_agent.cli.main.backfill_football_data", fake_backfill)
    result = CliRunner().invoke(cli, ["backfill-odds", "--season", "2024-25"])
    assert result.exit_code == 0
    assert captured["season"] == "2024-25"
