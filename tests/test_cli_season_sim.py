from types import SimpleNamespace

from click.testing import CliRunner

from fpl_agent.cli.main import cli
from tests.test_transfer_search import _patch_expected_points_window, _seed_two_team_pool


def _patch_squad_rebuild(monkeypatch, player_ids):
    """season-sim now solves the wildcard/free-hit squad rebuild itself (to know
    which players the scenario draw must cover), which the 4-player test pool can't
    satisfy a real 15-man ILP with. Stubs it to a known set instead."""
    import fpl_agent.cli.main as main_mod

    fake = SimpleNamespace(squad=[SimpleNamespace(player_id=pid) for pid in player_ids])
    monkeypatch.setattr(main_mod, "_cached_optimise_squad", lambda conn, n_gw: fake)


def test_season_sim_runs_without_error(monkeypatch, db_conn):
    # Same non-monkeypatched-get_connection pattern as test_cli_transfer_search.py -
    # the cli() group callback opens/closes its own connection every invocation, see
    # that file's comment for the full explanation.
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)
    _patch_squad_rebuild(monkeypatch, [3, 4])

    import fpl_agent.cli.main as main_mod
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


def test_season_sim_samples_scenarios_for_the_full_superset_not_just_the_squad(monkeypatch, db_conn):
    """Regression test for the cross-task composition bug the whole-branch review found.

    sample_season_scenarios used to be called with --squad's own ids only, but three
    downstream consumers score players OUTSIDE that set via
    points_by_event_player.get((event, pid), 0.0):
      1. chips.py::_wildcard_trial_values scores a squad rebuilt from the ENTIRE
         player pool (players 3/4 here - unaffordable by transfer, so reachable only
         via the rebuild),
      2. chips.py::_advisory_hit_recommendations swaps in a hit candidate, which is a
         player outside the squad by definition (player 5 here),
      3. chips.py::_squad_ids_by_event reflects the beam search's own transfers.
    Any of those missing from the draw silently scored 0.0 on EVERY trial - which is
    what made wildcard/freehit marginal value provably <= 0 always, and the advisory
    hit layer structurally unable to fire. Asserting on the ids the sampler is asked
    for is the assertion that actually pins the fix, since the .get fallback means a
    gap is invisible in the output.
    """
    _seed_two_team_pool(db_conn)
    # A cheap strong forward - affordable as a hit-in for player 1/2 (both priced 50,
    # bank 0), unlike players 3/4 at 55. Gives the advisory/trajectory paths a real
    # out-of-squad player to reach for.
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
        "VALUES (5,5,'Cheap Strong',2,1,'a',0,'2026-01-01T00:00:00Z')"
    )
    db_conn.execute(
        "INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) "
        "VALUES (5, 50, '2026-01-01T00:00:00Z', NULL)"
    )
    db_conn.commit()

    from fpl_agent.optimization import transfers as transfers_mod

    monkeypatch.setattr(
        transfers_mod, "expected_points_window",
        lambda conn, player_id, n_gw, from_event=None: SimpleNamespace(
            total_median={1: 3.0, 2: 3.0, 3: 6.0, 4: 6.0, 5: 9.0}[player_id]
        ),
    )
    _patch_squad_rebuild(monkeypatch, [3, 4])

    import fpl_agent.cli.main as main_mod
    from fpl_agent.models.scenario_engine import ScenarioOutcome

    sampled_ids: set[int] = set()

    def recording_sample(conn, squad_ids, from_event, horizon_gw, n_trials=1000, rng=None):
        sampled_ids.update(squad_ids)
        return [
            ScenarioOutcome(trial_index=i, points_by_event_player={
                (e, pid): 5.0 for e in range(from_event, from_event + horizon_gw) for pid in squad_ids
            })
            for i in range(n_trials)
        ]

    monkeypatch.setattr(main_mod, "sample_season_scenarios", recording_sample)

    runner = CliRunner()
    result = runner.invoke(cli, ["season-sim", "--squad", "1,2", "--trials", "10", "--horizon", "2"])

    assert result.exit_code == 0, result.output
    assert {1, 2} <= sampled_ids  # the squad itself, as before
    assert {3, 4} <= sampled_ids, f"rebuilt-squad members missing from the draw: {sampled_ids}"
    assert 5 in sampled_ids, f"out-of-squad hit candidate missing from the draw: {sampled_ids}"


def test_season_sim_excludes_already_used_chips(monkeypatch, db_conn):
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)
    _patch_squad_rebuild(monkeypatch, [3, 4])
    db_conn.execute(
        "INSERT INTO chip_windows (id,name,number,start_event,stop_event,chip_type,season,updated_at) "
        "VALUES (1,'bboost',1,1,19,'team','2026-27','t0')"
    )
    db_conn.commit()

    import fpl_agent.cli.main as main_mod
    from fpl_agent.models.scenario_engine import ScenarioOutcome

    def fake_sample(conn, squad_ids, from_event, horizon_gw, n_trials=1000, rng=None):
        return [
            ScenarioOutcome(trial_index=i, points_by_event_player={
                (e, pid): 5.0 for e in range(from_event, from_event + horizon_gw) for pid in squad_ids
            })
            for i in range(n_trials)
        ]

    monkeypatch.setattr(main_mod, "sample_season_scenarios", fake_sample)

    captured = {}

    def capture_schedule(conn, squad_ids, trajectory, windows, scenario_draw, used_chip_names=frozenset()):
        captured["used_chip_names"] = used_chip_names
        from fpl_agent.optimization.chips import ChipSchedule
        return ChipSchedule(baseline_schedule=(), advisory_hit_recommendations=(), total_expected_value=0.0)

    monkeypatch.setattr(main_mod, "schedule_chips", capture_schedule)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["season-sim", "--squad", "1,2", "--trials", "10", "--horizon", "2", "--used-chips", "bboost, wildcard"]
    )

    assert result.exit_code == 0, result.output
    assert captured["used_chip_names"] == {"bboost", "wildcard"}


def test_season_sim_auto_detects_used_chips_from_a_synced_real_team(monkeypatch, db_conn):
    """Real gap closed 2026-08-21: --used-chips previously always had to be
    typed in by hand. Omitting it now auto-detects real played chips from a
    synced `fpl my-team` entry."""
    _seed_two_team_pool(db_conn)
    _patch_expected_points_window(monkeypatch)
    _patch_squad_rebuild(monkeypatch, [3, 4])
    db_conn.execute(
        "INSERT INTO chip_windows (id,name,number,start_event,stop_event,chip_type,season,updated_at) "
        "VALUES (1,'bboost',1,1,19,'team','2026-27','t0')"
    )
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('my_team_entry_id', '7378572', 't0')"
    )
    db_conn.execute(
        "INSERT INTO my_team_picks (entry_id, event, player_id, squad_slot, multiplier, is_captain, "
        "is_vice_captain, active_chip, retrieved_at) VALUES (7378572, 1, 1, 1, 1, 0, 0, 'bboost', 't0')"
    )
    db_conn.commit()

    import fpl_agent.cli.main as main_mod
    from fpl_agent.models.scenario_engine import ScenarioOutcome

    def fake_sample(conn, squad_ids, from_event, horizon_gw, n_trials=1000, rng=None):
        return [
            ScenarioOutcome(trial_index=i, points_by_event_player={
                (e, pid): 5.0 for e in range(from_event, from_event + horizon_gw) for pid in squad_ids
            })
            for i in range(n_trials)
        ]

    monkeypatch.setattr(main_mod, "sample_season_scenarios", fake_sample)

    captured = {}

    def capture_schedule(conn, squad_ids, trajectory, windows, scenario_draw, used_chip_names=frozenset()):
        captured["used_chip_names"] = used_chip_names
        from fpl_agent.optimization.chips import ChipSchedule
        return ChipSchedule(baseline_schedule=(), advisory_hit_recommendations=(), total_expected_value=0.0)

    monkeypatch.setattr(main_mod, "schedule_chips", capture_schedule)

    runner = CliRunner()
    result = runner.invoke(cli, ["season-sim", "--squad", "1,2", "--trials", "10", "--horizon", "2"])  # no --used-chips

    assert result.exit_code == 0, result.output
    assert captured["used_chip_names"] == {"bboost"}
    assert "auto-detected used chips" in result.output
