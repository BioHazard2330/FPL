# tests/test_e2e_plan1a_lifecycle.py
"""Proves Plan 1a composes end to end: sync (with momentum/total_players) ->
price forecast -> beam search -> CLI --search -> decision journal. Same bar
test_e2e_pillar0_lifecycle.py already set for Pillar 0."""
from click.testing import CliRunner

from fpl_agent.cli.main import cli
from fpl_agent.ingestion.sync import sync_total_players, sync_transfer_momentum_history
from fpl_agent.models.price_forecast import classify_price_change
from fpl_agent.normalization.fpl_core import normalize_player_transfer_momentum
from fpl_agent.optimization.transfers import search_transfer_sequences
from tests.test_transfer_search import _patch_expected_points_window, _seed_two_team_pool


def test_plan1a_pipeline_composes_end_to_end(db_conn, monkeypatch):
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    bootstrap = {
        "total_players": 1000000,
        "elements": [
            {"id": 1, "transfers_in_event": 100, "transfers_out_event": 9000,
             "transfers_in": 100, "transfers_out": 9000},
            {"id": 3, "transfers_in_event": 9000, "transfers_out_event": 100,
             "transfers_in": 9000, "transfers_out": 100},
        ],
    }
    sync_total_players(db_conn, bootstrap, "2026-08-15T10:00:00Z")
    changed = sync_transfer_momentum_history(
        db_conn, normalize_player_transfer_momentum(bootstrap), "2026-08-15T10:00:00Z"
    )
    db_conn.commit()
    assert changed == 2

    assert classify_price_change(db_conn, 1).direction == "FALL_LIKELY"
    assert classify_price_change(db_conn, 3).direction == "RISE_LIKELY"

    sequences = search_transfer_sequences(
        db_conn, squad_ids=[1, 2], free_transfers=1, bank_tenths=100, horizon_gw=2, beam_width=4,
    )
    assert len(sequences) > 0

    # Deliberately NOT monkeypatching fpl_agent.cli.main.get_connection to
    # return db_conn directly: the cli() group callback (unrelated to this
    # task, untouched) itself does get_connection() -> run_migrations() ->
    # conn.close() on every invocation. If get_connection were patched to
    # always hand back the literal same db_conn object, that callback would
    # close it before the transfers command body even runs (verified by
    # hand - same failure test_cli_transfer_search.py's own comment already
    # documents for the pre-existing non-search path). The db_conn fixture
    # already monkeypatches DATA_DIR/DB_PATH inside fpl_agent.database.connection,
    # so the real (unpatched) get_connection() naturally opens a fresh
    # connection to the same temp db file on each call - exactly how it
    # behaves in production - which sidesteps the premature-close issue while
    # still exercising the same seeded, committed data.
    runner = CliRunner()
    result = runner.invoke(cli, ["transfers", "--squad", "1,2", "--search", "--horizon", "2"])
    assert result.exit_code == 0, result.output
    assert "decision_id=" in result.output
