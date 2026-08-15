from click.testing import CliRunner

from fpl_agent.cli.main import cli


def test_backfill_xg_invokes_understat_backfill(monkeypatch):
    captured = {}

    def fake_backfill(conn, season, **kwargs):
        captured["season"] = season
        return {"matches_processed": 0, "player_rows_inserted": 0}

    monkeypatch.setattr("fpl_agent.cli.main.backfill_understat", fake_backfill)
    result = CliRunner().invoke(cli, ["backfill-xg", "--season", "2024-25"])
    assert result.exit_code == 0
    assert captured["season"] == "2024-25"
