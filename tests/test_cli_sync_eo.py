from click.testing import CliRunner

from fpl_agent.cli.main import cli


def test_sync_eo_reports_result(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(
        main_mod, "sample_effective_ownership",
        lambda conn, event, target_sample_size, force: {
            "skipped": False, "event": event, "sample_size": 700, "players_sampled": 450, "managers_failed": 12,
        },
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-eo", "--event", "3"])

    assert result.exit_code == 0, result.output
    assert "sample size      700" in result.output
    assert "players sampled  450" in result.output


def test_sync_eo_reports_skip(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod

    monkeypatch.setattr(
        main_mod, "sample_effective_ownership",
        lambda conn, event, target_sample_size, force: {
            "skipped": True, "event": event, "sample_size": 0, "players_sampled": 0, "managers_failed": 0,
        },
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-eo", "--event", "3"])

    assert result.exit_code == 0
    assert "already sampled" in result.output


def test_sync_eo_reports_validation_error_cleanly(monkeypatch, db_conn):
    import fpl_agent.cli.main as main_mod

    def raise_not_locked(conn, event, target_sample_size, force):
        raise ValueError(f"event {event} has not locked yet (deadline still ahead) - picks aren't available")

    monkeypatch.setattr(main_mod, "sample_effective_ownership", raise_not_locked)

    runner = CliRunner()
    result = runner.invoke(cli, ["sync-eo", "--event", "1"])

    assert result.exit_code == 1
    assert "has not locked yet" in result.output
