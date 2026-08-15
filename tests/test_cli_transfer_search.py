# tests/test_cli_transfer_search.py
from click.testing import CliRunner

from fpl_agent.cli.main import cli
from tests.test_transfer_search import _patch_expected_points_window, _seed_two_team_pool


def test_transfers_search_flag_runs_without_error(monkeypatch, db_conn):
    # Deliberately NOT monkeypatching fpl_agent.cli.main.get_connection to
    # return db_conn directly: the cli() group callback (unrelated to this
    # task, untouched) itself does get_connection() -> run_migrations() ->
    # conn.close() on every invocation. If get_connection were patched to
    # always hand back the literal same db_conn object, that callback would
    # close it before the transfers command body even runs, and the SAME
    # failure reproduces on the pre-existing non-search path too (verified by
    # hand - this is not something the --search code path introduces). The
    # db_conn fixture already monkeypatches DATA_DIR/DB_PATH inside
    # fpl_agent.database.connection, so the real (unpatched) get_connection()
    # naturally opens a fresh connection to the same temp db file on each
    # call - exactly how it behaves in production - which sidesteps the
    # premature-close issue while still exercising the same seeded data.

    # reuse the exact seeding + expected_points_window mock from
    # tests/test_transfer_search.py (Task 5) rather than duplicating either -
    # the mock matters here too, the CLI path goes through the same real
    # search_transfer_sequences -> best_transfer_for_player -> evaluate_transfer
    # -> expected_points_window chain, unmocked it would hit the same deep
    # Pillar-0-pipeline dependency problem Task 5's testing note explains.
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["transfers", "--squad", "1,2", "--search", "--horizon", "2", "--beam-width", "2"],
    )
    assert result.exit_code == 0, result.output
    assert "decision_id=" in result.output
