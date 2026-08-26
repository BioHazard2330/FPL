import fpl_agent.optimization.post_gw_pipeline as pipeline_mod
from fpl_agent.optimization.chips import ChipWindow
from fpl_agent.optimization.decision_engine import CaptainAction, SquadDecision, TransferAction
from fpl_agent.optimization.locked_squad import LockedSquadState
from fpl_agent.optimization.squad import PlayerCandidate, StartingXI


def _candidate(pid, web_name="P"):
    return PlayerCandidate(
        player_id=pid, web_name=web_name, position="MID", team_id=1, team_short="T1",
        price_tenths=50, xp=4.0, median=4.0, floor=2.0, ceiling=6.0, confidence="MEDIUM", expected_minutes=80.0,
    )


def _locked(squad_ids=(1, 2, 3)):
    xi = StartingXI(starting=[_candidate(pid) for pid in squad_ids], bench=[], captain=_candidate(1), vice_captain=None)
    return LockedSquadState(
        source="synced_real", event=1, squad_ids=frozenset(squad_ids), xi=xi,
        bank_tenths=10, squad_value_tenths=500, decision_id=None,
    )


def _fake_decision():
    return SquadDecision(
        captain_action=CaptainAction("keep", None, None, 0.0),
        transfer_action=TransferAction("keep", None, 0.0),
        risks=[],
    )


def _stub_common(monkeypatch, locked, decision):
    monkeypatch.setattr(pipeline_mod, "get_locked_squad", lambda conn: locked)
    monkeypatch.setattr(pipeline_mod, "evaluate_locked_squad", lambda conn, locked_: decision)
    monkeypatch.setattr(pipeline_mod, "eligible_chips", lambda conn, event: [
        ChipWindow("bboost", 1, 1, 19, "team", True),
    ])
    monkeypatch.setattr(pipeline_mod, "bench_boost_value", lambda conn, squad_ids: 5.0)
    monkeypatch.setattr(pipeline_mod, "triple_captain_value", lambda conn, squad_ids: 3.0)
    monkeypatch.setattr(pipeline_mod, "wildcard_value", lambda conn, squad_ids, n_gw=5: 1.0)
    monkeypatch.setattr(pipeline_mod, "freehit_value", lambda conn, squad_ids: 0.5)
    monkeypatch.setattr(pipeline_mod, "refresh_in_progress_matches", lambda conn: {"refreshed": 0, "skipped": 0, "failed": 0})


def test_bails_out_honestly_without_a_locked_squad(db_conn, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "get_locked_squad", lambda conn: None)

    result = pipeline_mod.run_post_gw_pipeline(db_conn, event=1)

    assert result.ran is False
    assert "no locked squad" in result.reason


def test_runs_and_marks_done_for_the_event(db_conn, monkeypatch):
    _stub_common(monkeypatch, _locked(), _fake_decision())

    result = pipeline_mod.run_post_gw_pipeline(db_conn, event=1)

    assert result.ran is True
    assert result.decision_id is not None
    marker = db_conn.execute(
        "SELECT value FROM app_meta WHERE key='post_gw_pipeline_done_event'"
    ).fetchone()
    assert marker["value"] == "1"


def test_logs_a_real_decision_with_captain_transfer_chip_detail(db_conn, monkeypatch):
    _stub_common(monkeypatch, _locked(), _fake_decision())

    result = pipeline_mod.run_post_gw_pipeline(db_conn, event=1)

    row = db_conn.execute(
        "SELECT decision_type, detail FROM decisions WHERE id=?", (result.decision_id,)
    ).fetchone()
    assert row["decision_type"] == "post_gw_plan"
    import json
    detail = json.loads(row["detail"])
    assert detail["captain"]["kind"] == "keep"
    assert detail["transfer"]["kind"] == "keep"
    assert detail["bench_boost"] == 5.0
    assert detail["wildcard_5gw"] == 1.0

    # Also logs a "chip" decision, matching the existing Chip Strategy
    # panel's own latest_decision_of_type(conn, "chip") read shape.
    chip_row = db_conn.execute(
        "SELECT detail FROM decisions WHERE decision_type='chip' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    chip_detail = json.loads(chip_row["detail"])
    assert chip_detail["wildcard_5gw"] == 1.0
    assert chip_detail["free_hit"] == 0.5


def test_backfills_a_full_time_match_missing_an_analysis_job(db_conn, monkeypatch):
    _stub_common(monkeypatch, _locked(), _fake_decision())
    db_conn.execute(
        "INSERT INTO teams (id, code, name, short_name, strength_overall_home, strength_overall_away, "
        "strength_attack_home, strength_attack_away, strength_defence_home, strength_defence_away, pulse_id, updated_at) "
        "VALUES (1,1,'A','A',3,3,0,0,0,0,1,'t0'), (2,2,'B','B',3,3,0,0,0,0,2,'t0')"
    )
    db_conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, home_team_id, away_team_id, status, "
        "home_score, away_score, retrieved_at) VALUES (1, 'm1', 1, 2, 'FULL_TIME', 2, 1, 't0')"
    )
    db_conn.commit()

    pipeline_mod.run_post_gw_pipeline(db_conn, event=1)

    job = db_conn.execute(
        "SELECT status FROM qualitative_analysis_jobs WHERE match_id=1 AND phase='FULL_TIME'"
    ).fetchone()
    assert job is not None
    assert job["status"] == "pending"


def test_maybe_run_is_a_real_noop_when_lifecycle_is_not_gw_finished(db_conn, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "compute_gw_lifecycle_state", lambda conn: None)

    assert pipeline_mod.maybe_run_post_gw_pipeline(db_conn) is None


def test_maybe_run_triggers_the_real_pipeline_when_gw_finished(db_conn, monkeypatch):
    from fpl_agent.models.gw_lifecycle import GWLifecycleState

    _stub_common(monkeypatch, _locked(), _fake_decision())
    monkeypatch.setattr(
        pipeline_mod, "compute_gw_lifecycle_state",
        lambda conn: GWLifecycleState(event=1, state="GW_FINISHED", deadline_utc="t0", any_started=True, all_finished=True, data_valid=True),
    )

    result = pipeline_mod.maybe_run_post_gw_pipeline(db_conn)

    assert result is not None
    assert result.ran is True


def test_maybe_run_reassesses_when_a_real_material_change_lands_after_the_last_plan(db_conn, monkeypatch):
    """Section I's real gap: once READY_FOR_NEXT_DEADLINE, a genuine
    HIGH-severity change_event on a locked-squad player (e.g. a real
    confirmed-benched lineup) after the last pipeline run must trigger a
    real reassessment - not sit stale until the next gameweek."""
    from fpl_agent.models.gw_lifecycle import GWLifecycleState

    _stub_common(monkeypatch, _locked(), _fake_decision())
    monkeypatch.setattr(
        pipeline_mod, "compute_gw_lifecycle_state",
        lambda conn: GWLifecycleState(event=1, state="READY_FOR_NEXT_DEADLINE", deadline_utc="t0", any_started=True, all_finished=True, data_valid=True),
    )
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('post_gw_pipeline_done_event', '1', '2026-08-22T10:00:00Z')"
    )
    db_conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, "
        "sources, confidence, severity, action_required) VALUES "
        "('lineup_confirmed', 'player', 1, 'PREDICTED_START', 'CONFIRMED_BENCHED', '2026-08-26T09:00:00Z', "
        "'fotmob', 'CONFIRMED', 'HIGH', 1)"
    )
    db_conn.commit()

    result = pipeline_mod.maybe_run_post_gw_pipeline(db_conn)

    assert result is not None
    assert result.ran is True


def test_maybe_run_stays_a_noop_for_a_real_but_low_severity_change(db_conn, monkeypatch):
    """Materiality, not every event - a real but low-severity change_event
    (e.g. a routine price move that never escalated) must not trigger a
    full strategic re-solve, matching section S's "do not let every headline
    trigger a model overhaul" rule."""
    from fpl_agent.models.gw_lifecycle import GWLifecycleState

    _stub_common(monkeypatch, _locked(), _fake_decision())
    monkeypatch.setattr(
        pipeline_mod, "compute_gw_lifecycle_state",
        lambda conn: GWLifecycleState(event=1, state="READY_FOR_NEXT_DEADLINE", deadline_utc="t0", any_started=True, all_finished=True, data_valid=True),
    )
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('post_gw_pipeline_done_event', '1', '2026-08-22T10:00:00Z')"
    )
    db_conn.execute(
        "INSERT INTO change_events (event_type, entity, entity_id, old_value, new_value, detected_at, "
        "sources, confidence, severity, action_required) VALUES "
        "('price_change', 'player', 1, '50', '51', '2026-08-26T09:00:00Z', "
        "'fpl_api', 'CONFIRMED', 'LOW', 0)"
    )
    db_conn.commit()

    result = pipeline_mod.maybe_run_post_gw_pipeline(db_conn)

    assert result is None


def test_maybe_run_second_call_is_a_real_noop_once_ready(db_conn, monkeypatch):
    """Idempotency/restart-recovery: once the real lifecycle state reports
    READY_FOR_NEXT_DEADLINE (the pipeline already completed for this event),
    a second call must not re-run anything - the daemon calling this on
    every scheduled tick must stay cheap."""
    from fpl_agent.models.gw_lifecycle import GWLifecycleState

    _stub_common(monkeypatch, _locked(), _fake_decision())
    monkeypatch.setattr(
        pipeline_mod, "compute_gw_lifecycle_state",
        lambda conn: GWLifecycleState(event=1, state="READY_FOR_NEXT_DEADLINE", deadline_utc="t0", any_started=True, all_finished=True, data_valid=True),
    )

    result = pipeline_mod.maybe_run_post_gw_pipeline(db_conn)

    assert result is None
