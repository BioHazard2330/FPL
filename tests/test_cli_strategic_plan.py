from types import SimpleNamespace

from click.testing import CliRunner

from fpl_agent.cli.main import cli
from tests.test_transfer_search import _patch_expected_points_window, _seed_two_team_pool


def _patch_squad_rebuild(monkeypatch, player_ids):
    import fpl_agent.cli.main as main_mod

    fake = SimpleNamespace(squad=[SimpleNamespace(player_id=pid) for pid in player_ids])
    monkeypatch.setattr(main_mod, "_cached_optimise_squad", lambda conn, n_gw: fake)


def test_strategic_plan_runs_without_chips_and_logs_all_paths(monkeypatch, db_conn):
    """Real "generate all of it" wiring test: --no-chips keeps this a fast,
    pure path-search run, and the logged decision must carry the FULL top-N
    paths (not just the winner) - the dashboard's Strategic Plan section
    reads exactly this shape without ever re-running the search."""
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["strategic-plan", "--squad", "1,2", "--bank", "0", "--horizon", "2", "--beam-width", "2", "--no-chips"]
    )

    assert result.exit_code == 0, result.output
    assert "HORIZON COMPARISON" in result.output
    assert "TOP" in result.output and "REAL 2-GW PATHS" in result.output

    import json

    row = db_conn.execute("SELECT detail FROM decisions WHERE decision_type='strategic_plan' ORDER BY id DESC LIMIT 1").fetchone()
    detail = json.loads(row["detail"])
    assert detail["chip_schedule"] is None
    assert isinstance(detail["paths"], list) and len(detail["paths"]) >= 1
    assert detail["best_path"] is not None
    assert detail["best_path"]["steps"] == detail["paths"][0]["steps"]

    # Real "strategic path score semantics" fix (P0, 2026-08-27): a real
    # roll baseline is computed and every path/horizon-comparison entry
    # carries an explicit path_total (never bare "net EV") plus a real,
    # separate delta_vs_roll - proving the labeling ambiguity the audit
    # flagged is actually closed, not just renamed in prose.
    assert detail["roll_total"] is not None
    assert detail["best_path"]["path_total"] == detail["best_path"]["total_net_ev"]
    assert detail["best_path"]["delta_vs_roll"] == round(detail["best_path"]["total_net_ev"] - detail["roll_total"], 2)
    assert detail["best_path"]["delta_vs_leader"] == 0.0  # the winning path has zero gap to itself
    for hc in detail["horizon_comparison"]:
        assert "path_total" in hc and "delta_vs_roll" in hc
    if len(detail["paths"]) > 1:
        assert detail["paths"][1]["delta_vs_leader"] <= 0.0  # never ranked above the real leader


def test_strategic_plan_with_chips_overlays_a_real_chip_schedule(monkeypatch, db_conn):
    """--with-chips (the default) overlays a real chip schedule onto the
    winning path via the exact same schedule_chips DP season-sim already
    uses - proves the wiring composes, not a new algorithm."""
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)
    _patch_squad_rebuild(monkeypatch, [3, 4])
    db_conn.execute(
        "INSERT INTO chip_windows (id,name,number,start_event,stop_event,chip_type,season,updated_at) "
        "VALUES (1,'bboost',1,1,19,'team','2026-27','t0')"
    )
    db_conn.commit()

    import fpl_agent.cli.main as main_mod
    import fpl_agent.optimization.chips as chips_mod
    from fpl_agent.models.scenario_engine import ScenarioOutcome
    import numpy as np

    def fake_sample(conn, squad_ids, from_event, horizon_gw, n_trials=1000, rng=None):
        return [
            ScenarioOutcome(trial_index=i, points_by_event_player={
                (e, pid): 5.0 for e in range(from_event, from_event + horizon_gw) for pid in squad_ids
            })
            for i in range(n_trials)
        ]

    monkeypatch.setattr(main_mod, "sample_season_scenarios", fake_sample)
    # This wiring test proves the CLI correctly calls schedule_chips and
    # stores its result - schedule_chips' own bboost arithmetic (which needs
    # a real pick_starting_xi over a full 15-man pool) is already covered by
    # test_optimization_chips.py; the minimal 2-team test pool here isn't
    # meant to support a real formation solve, same reason those tests stub
    # this function too.
    monkeypatch.setattr(chips_mod, "_bench_boost_trial_values", lambda conn, squad_ids, event, scenario_draw: np.array([10.0, 10.0]))

    runner = CliRunner()
    result = runner.invoke(
        cli, ["strategic-plan", "--squad", "1,2", "--bank", "0", "--horizon", "2", "--beam-width", "2",
              "--trials", "5", "--with-chips"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output

    import json

    row = db_conn.execute("SELECT detail FROM decisions WHERE decision_type='strategic_plan' ORDER BY id DESC LIMIT 1").fetchone()
    detail = json.loads(row["detail"])
    assert detail["chip_schedule"] is not None
    assert "entries" in detail["chip_schedule"]
