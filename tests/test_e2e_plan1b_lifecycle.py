# tests/test_e2e_plan1b_lifecycle.py
from click.testing import CliRunner

from fpl_agent.cli.main import cli


def _seed_minimal_pool(conn):
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, "
        "squad_min_play, squad_max_play, updated_at) VALUES "
        "(1,'Goalkeeper','GKP','Goalkeepers',1,1,'t0'), (4,'Forward','FWD','Forwards',1,3,'t0')"
    )
    conn.executemany(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?,'t0')",
        [(1, 100, "Team A", "TMA"), (2, 101, "Team B", "TMB")],
    )
    conn.executemany(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) VALUES (?,?,?,?,?,'a','t0')",
        [(1, 1, "GK", 1, 1), (2, 2, "Striker", 1, 4), (3, 3, "OppFwd", 2, 4)],
    )
    conn.executemany(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, updated_at) VALUES (?,?,?,0,0,0,0,0,'t0')",
        [(10, "GW10", "t0"), (11, "GW11", "t0")],
    )
    conn.executemany(
        "INSERT INTO fixtures (id, code, event, team_h, team_a, finished, started, updated_at) VALUES (?,?,?,?,?,0,0,'t0')",
        [(1, 1, 10, 1, 2), (2, 2, 11, 1, 2)],
    )
    conn.execute(
        "INSERT INTO rules (rule_key,season,version,effective_date,source,value) VALUES "
        "('scoring.goals_scored.FWD','2026-27',1,'t0','fpl_api','4'), "
        "('scoring.assists','2026-27',1,'t0','fpl_api','3'), "
        "('scoring.yellow_cards','2026-27',1,'t0','fpl_api','-1')"
    )
    conn.executemany(
        "INSERT INTO chip_windows (id,name,number,start_event,stop_event,chip_type,season,updated_at) VALUES (?,?,?,?,?,?,?,'t0')",
        [(1, "bboost", 1, 1, 19, "team", "2026-27")],
    )
    conn.commit()


def test_plan1b_pipeline_composes_end_to_end(db_conn, monkeypatch):
    _seed_minimal_pool(db_conn)

    from fpl_agent.models.scenario_engine import sample_season_scenarios

    outcomes = sample_season_scenarios(db_conn, squad_ids=[1, 2], from_event=10, horizon_gw=2, n_trials=100)
    assert len(outcomes) == 100
    assert all((10, 1) in o.points_by_event_player and (11, 2) in o.points_by_event_player for o in outcomes)

    from fpl_agent.optimization.chips import ChipWindow, schedule_chips
    from fpl_agent.optimization.transfers import TransferSequence, TransferSequenceStep

    trajectory = TransferSequence(
        steps=(TransferSequenceStep(event=10, player_out_id=None, player_out_name=None, player_in_id=None, player_in_name=None, uses_hit=False),),
        final_squad_ids=(1, 2), final_free_transfers=1, final_bank_tenths=0,
        total_net_ev=0.0, tiebreak_adjustment=0.0,
    )
    windows = [ChipWindow(name="bboost", number=1, start_event=1, stop_event=19, chip_type="team", eligible_now=True)]
    schedule = schedule_chips(db_conn, [1, 2], trajectory, windows, outcomes)
    assert schedule.total_expected_value >= 0.0  # bench boost of an all-starting-XI-eligible squad is >= 0

    import fpl_agent.cli.main as main_mod
    monkeypatch.setattr(main_mod, "sample_season_scenarios", lambda *a, **kw: outcomes)

    runner = CliRunner()
    result = runner.invoke(cli, ["season-sim", "--squad", "1,2", "--trials", "100", "--horizon", "2"])
    assert result.exit_code == 0, result.output
    assert "decision_id=" in result.output

    decision_id = int(result.output.strip().splitlines()[-1].split("decision_id=")[1])
    row = db_conn.execute("SELECT decision_type FROM decisions WHERE id=?", (decision_id,)).fetchone()
    assert row["decision_type"] == "season_sim"
