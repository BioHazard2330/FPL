from click.testing import CliRunner

from fpl_agent.cli.main import cli
from tests.test_transfer_search import _patch_expected_points_window, _seed_two_team_pool


def test_season_sim_runs_without_error(monkeypatch, db_conn):
    # Same non-monkeypatched-get_connection pattern as test_cli_transfer_search.py -
    # the cli() group callback opens/closes its own connection every invocation, see
    # that file's comment for the full explanation.
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    import fpl_agent.cli.main as main_mod
    import numpy as np
    # Stub the (expensive, Pillar-0-deep) scenario sampler so this stays a pure CLI
    # wiring test - Task 4's own tests already cover sampling correctness.
    from fpl_agent.models.scenario_engine import ScenarioOutcome

    def fake_sample(conn, squad_ids, from_event, horizon_gw, n_trials=1000, rng=None):
        return [
            ScenarioOutcome(trial_index=i, points_by_event_player={
                (e, pid): 5.0 for e in range(from_event, from_event + horizon_gw) for pid in squad_ids
            })
            for i in range(n_trials)
        ]

    monkeypatch.setattr(main_mod, "sample_season_scenarios", fake_sample)

    runner = CliRunner()
    result = runner.invoke(cli, ["season-sim", "--squad", "1,2", "--trials", "20", "--horizon", "2"])

    assert result.exit_code == 0, result.output
    assert "P10=" in result.output
    assert "decision_id=" in result.output
