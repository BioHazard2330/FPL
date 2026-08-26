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


def _seed_players_with_positions(conn, ids_positions):
    """ids_positions: list of (player_id, element_type_id, singular_name_short)."""
    conn.execute("INSERT INTO teams (id,code,name,short_name,updated_at) VALUES (1,1,'T1','T1','t0')")
    seen_types = {}
    for pid, et_id, et_short in ids_positions:
        if et_id not in seen_types:
            conn.execute(
                "INSERT INTO element_types (id,singular_name,singular_name_short,plural_name,updated_at) "
                "VALUES (?,?,?,?,'t0')",
                (et_id, et_short, et_short, et_short + "s"),
            )
            seen_types[et_id] = True
        conn.execute(
            "INSERT INTO players (id,code,web_name,team_id,element_type,status,updated_at) "
            "VALUES (?,?,?,1,?,'a','t0')",
            (pid, pid, f"P{pid}", et_id),
        )
    conn.commit()


def _insert_prediction_outcome(conn, player_id, event, season, predicted_median, actual_points,
                                predicted_expected_minutes=80.0, predicted_minutes_basis="current_season_only",
                                predicted_availability="FIT"):
    conn.execute(
        "INSERT INTO prediction_outcomes (player_id, event, season, predicted_median, predicted_expected_minutes, "
        "predicted_minutes_basis, predicted_availability, actual_points, predicted_at) "
        "VALUES (?,?,?,?,?,?,?,?,'t0')",
        (player_id, event, season, predicted_median, predicted_expected_minutes,
         predicted_minutes_basis, predicted_availability, actual_points),
    )
    conn.commit()


def test_record_predictions_captures_minutes_basis_and_availability(db_conn, monkeypatch):
    from types import SimpleNamespace

    _seed_players_with_positions(db_conn, [(1, 1, "MID")])
    monkeypatch.setattr(calibration_mod, "current_season", lambda conn: "2026-27")
    monkeypatch.setattr(
        calibration_mod, "expected_points",
        lambda conn, pid, n_gw=1: SimpleNamespace(
            median=4.0, floor=1.0, ceiling=8.0, confidence="MEDIUM", expected_minutes=80.0, model_version="calibrated-v2",
        ),
    )
    monkeypatch.setattr(
        calibration_mod, "expected_minutes",
        lambda conn, pid: SimpleNamespace(basis="cross_league_prior_new_signing"),
    )
    monkeypatch.setattr(calibration_mod, "_predicted_availability", lambda conn, pid: "DOUBTFUL")

    calibration_mod.record_predictions_for_locked_squad(db_conn, event=1, squad_ids=[1])

    row = db_conn.execute(
        "SELECT predicted_minutes_basis, predicted_availability FROM prediction_outcomes WHERE player_id=1"
    ).fetchone()
    assert row["predicted_minutes_basis"] == "cross_league_prior_new_signing"
    assert row["predicted_availability"] == "DOUBTFUL"


def test_segmented_accuracy_reports_real_cohorts_with_enough_samples(db_conn):
    _seed_players_with_positions(db_conn, [(1, 1, "MID"), (2, 1, "MID"), (3, 1, "MID")])
    for i, (pred, actual) in enumerate([(4.0, 6.0), (5.0, 3.0), (3.0, 3.0)], start=1):
        _insert_prediction_outcome(db_conn, player_id=i, event=1, season="2026-27",
                                    predicted_median=pred, actual_points=actual)

    results = calibration_mod.segmented_accuracy(db_conn, season="2026-27", min_samples=3)

    overall = next(r for r in results if r.cohort == "overall")
    assert overall.n == 3
    assert overall.mae == round((2.0 + 2.0 + 0.0) / 3, 4)
    position = next(r for r in results if r.cohort == "position:MID")
    assert position.n == 3


def test_segmented_accuracy_omits_a_cohort_below_the_minimum_sample_size(db_conn):
    _seed_players_with_positions(db_conn, [(1, 1, "MID")])
    _insert_prediction_outcome(db_conn, player_id=1, event=1, season="2026-27",
                                predicted_median=4.0, actual_points=6.0)

    results = calibration_mod.segmented_accuracy(db_conn, season="2026-27", min_samples=3)

    assert results == []  # honest silence, not a misleading n=1 MAE


def test_segmented_accuracy_separates_cold_start_from_established(db_conn):
    _seed_players_with_positions(db_conn, [(1, 1, "MID"), (2, 1, "MID"), (3, 1, "MID"),
                                            (4, 1, "MID"), (5, 1, "MID"), (6, 1, "MID")])
    for pid in (1, 2, 3):
        _insert_prediction_outcome(db_conn, player_id=pid, event=1, season="2026-27",
                                    predicted_median=1.0, actual_points=5.0,  # real, large error
                                    predicted_minutes_basis="cross_league_prior_new_signing")
    for pid in (4, 5, 6):
        _insert_prediction_outcome(db_conn, player_id=pid, event=1, season="2026-27",
                                    predicted_median=4.0, actual_points=4.0,  # real, perfect
                                    predicted_minutes_basis="current_season_only")

    results = {r.cohort: r for r in calibration_mod.segmented_accuracy(db_conn, season="2026-27", min_samples=3)}

    assert results["cohort:new_transfer_cold_start"].mae == 4.0
    assert results["cohort:established"].mae == 0.0
