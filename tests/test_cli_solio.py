from click.testing import CliRunner

import fpl_agent.ingestion.solio_source as solio_mod
from fpl_agent.cli.main import cli


def test_solio_sync_cmd_reports_skip_when_fresh(db_conn, monkeypatch):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('solio_last_synced_at', ?, ?)", (now, now)
    )
    db_conn.commit()

    result = CliRunner().invoke(cli, ["solio-sync"])
    assert result.exit_code == 0, result.output
    assert "skipped" in result.output


def test_solio_sync_cmd_reports_fetch_error(db_conn, monkeypatch):
    monkeypatch.setattr(
        solio_mod, "fetch_solio_payload",
        lambda: (_ for _ in ()).throw(solio_mod.SolioFetchError("real network failure")),
    )
    result = CliRunner().invoke(cli, ["solio-sync", "--force"])
    assert result.exit_code == 1
    assert "solio-sync failed" in result.output


def test_model_benchmark_cmd_errors_cleanly_without_a_snapshot(db_conn):
    result = CliRunner().invoke(cli, ["model-benchmark"])
    assert result.exit_code == 1
    assert "no Solio snapshot yet" in result.output
