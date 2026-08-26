from types import SimpleNamespace

import fpl_agent.models.calibration as calibration_mod


def _seed_players(conn, ids):
    conn.execute("INSERT INTO teams (id,code,name,short_name,updated_at) VALUES (1,1,'T1','T1','t0')")
    conn.execute(
        "INSERT INTO element_types (id,singular_name,singular_name_short,plural_name,updated_at) "
        "VALUES (1,'Midfielder','MID','Midfielders','t0')"
    )
    for pid in ids:
        conn.execute(
            "INSERT INTO players (id,code,web_name,team_id,element_type,status,updated_at) "
            "VALUES (?,?,?,1,1,'a','t0')",
            (pid, pid, f"P{pid}"),
        )
    conn.commit()


def test_record_predictions_writes_once_per_player_event(db_conn, monkeypatch):
    _seed_players(db_conn, [1, 2])
    monkeypatch.setattr(calibration_mod, "current_season", lambda conn: "2026-27")
    monkeypatch.setattr(
        calibration_mod, "expected_points",
        lambda conn, pid, n_gw=1: SimpleNamespace(
            median=4.0, floor=1.0, ceiling=8.0, confidence="MEDIUM", expected_minutes=80.0, model_version="calibrated-v2",
        ),
    )

    n = calibration_mod.record_predictions_for_locked_squad(db_conn, event=1, squad_ids=[1, 2])
    assert n == 2
    rows = db_conn.execute("SELECT player_id, predicted_median FROM prediction_outcomes ORDER BY player_id").fetchall()
    assert [r["predicted_median"] for r in rows] == [4.0, 4.0]

    # A real, already-recorded prediction is never overwritten by a second call.
    monkeypatch.setattr(
        calibration_mod, "expected_points",
        lambda conn, pid, n_gw=1: SimpleNamespace(
            median=99.0, floor=1.0, ceiling=8.0, confidence="MEDIUM", expected_minutes=80.0, model_version="calibrated-v2",
        ),
    )
    n2 = calibration_mod.record_predictions_for_locked_squad(db_conn, event=1, squad_ids=[1, 2])
    assert n2 == 0
    still = db_conn.execute("SELECT predicted_median FROM prediction_outcomes WHERE player_id=1").fetchone()
    assert still["predicted_median"] == 4.0


def test_record_outcomes_creates_a_prediction_less_row_when_none_exists(db_conn, monkeypatch):
    """The honest GW1 state: this table didn't exist before GW1's deadline,
    so there's no real predicted_median to pair with - the real outcome
    still gets captured rather than silently dropped."""
    _seed_players(db_conn, [1])
    monkeypatch.setattr(calibration_mod, "current_season", lambda conn: "2026-27")
    db_conn.execute(
        "INSERT INTO player_stats_snapshot (player_id, retrieved_at, event_points, minutes, stats_hash) "
        "VALUES (1, 't0', 6, 75, 'h1')"
    )
    db_conn.commit()

    n = calibration_mod.record_outcomes_for_finished_event(db_conn, event=1, squad_ids=[1])
    assert n == 1
    row = db_conn.execute("SELECT actual_points, actual_minutes, predicted_median FROM prediction_outcomes WHERE player_id=1").fetchone()
    assert row["actual_points"] == 6
    assert row["actual_minutes"] == 75
    assert row["predicted_median"] is None


def test_record_outcomes_fills_in_an_existing_prediction_row(db_conn, monkeypatch):
    _seed_players(db_conn, [1])
    monkeypatch.setattr(calibration_mod, "current_season", lambda conn: "2026-27")
    db_conn.execute(
        "INSERT INTO prediction_outcomes (player_id, event, season, predicted_median, predicted_at) "
        "VALUES (1, 1, '2026-27', 3.5, 't0')"
    )
    db_conn.execute(
        "INSERT INTO player_stats_snapshot (player_id, retrieved_at, event_points, minutes, stats_hash) "
        "VALUES (1, 't0', 9, 90, 'h1')"
    )
    db_conn.commit()

    n = calibration_mod.record_outcomes_for_finished_event(db_conn, event=1, squad_ids=[1])
    assert n == 1
    row = db_conn.execute(
        "SELECT actual_points, predicted_median FROM prediction_outcomes WHERE player_id=1 AND event=1"
    ).fetchone()
    assert row["actual_points"] == 9
    assert row["predicted_median"] == 3.5  # the real prediction is preserved, not overwritten


def test_record_outcomes_captures_a_real_qualitative_and_user_signal(db_conn, monkeypatch):
    _seed_players(db_conn, [1])
    monkeypatch.setattr(calibration_mod, "current_season", lambda conn: "2026-27")
    db_conn.execute(
        "INSERT INTO player_stats_snapshot (player_id, retrieved_at, event_points, minutes, stats_hash) "
        "VALUES (1, 't0', 6, 75, 'h1')"
    )
    db_conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, home_team_id, away_team_id, status, "
        "home_score, away_score, retrieved_at) VALUES (1, 'm1', 1, 1, 'FULL_TIME', 1, 0, 't0')"
    )
    db_conn.execute(
        "INSERT INTO player_fpl_implications (match_id, player_id, signal, direction, reason, confidence, "
        "created_at, phase) VALUES (1, 1, 'ROLE', 'POSITIVE', 'started and played well', 'medium', 't0', 'FULL_TIME')"
    )
    db_conn.execute(
        "INSERT INTO user_observations (subject_type, subject_id, sentiment, note, created_at) "
        "VALUES ('player', 1, 'positive', 'bullish', 't0')"
    )
    db_conn.commit()

    calibration_mod.record_outcomes_for_finished_event(db_conn, event=1, squad_ids=[1])

    row = db_conn.execute(
        "SELECT qualitative_direction, qualitative_reason, user_sentiment, user_note FROM prediction_outcomes WHERE player_id=1"
    ).fetchone()
    assert row["qualitative_direction"] == "POSITIVE"
    assert row["qualitative_reason"] == "started and played well"
    assert row["user_sentiment"] == "positive"
    assert row["user_note"] == "bullish"


def test_record_functions_are_real_noops_for_an_empty_squad(db_conn):
    assert calibration_mod.record_predictions_for_locked_squad(db_conn, event=1, squad_ids=[]) == 0
    assert calibration_mod.record_outcomes_for_finished_event(db_conn, event=1, squad_ids=[]) == 0
