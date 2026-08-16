from types import SimpleNamespace

from fpl_agent.optimization import captaincy as captaincy_mod

_EP = {
    1: SimpleNamespace(position="MID", floor=3.0, median=6.0, ceiling=10.0, confidence="MEDIUM", expected_minutes=85.0),
    2: SimpleNamespace(position="DEF", floor=4.0, median=5.0, ceiling=9.0, confidence="HIGH", expected_minutes=90.0),
    3: SimpleNamespace(position="FWD", floor=1.0, median=3.0, ceiling=14.0, confidence="LOW", expected_minutes=45.0),
}


def _seed(conn):
    now = "t0"
    conn.execute(
        "INSERT INTO teams (id,code,name,short_name,strength_overall_home,strength_overall_away,"
        "strength_attack_home,strength_attack_away,strength_defence_home,strength_defence_away,pulse_id,updated_at) "
        "VALUES (1,1,'Home','HOM',3,3,0,0,0,0,1,?), (2,2,'Away','AWY',3,3,0,0,0,0,2,?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO element_types (id,singular_name,singular_name_short,plural_name,squad_min_play,"
        "squad_max_play,squad_select,updated_at) VALUES (1,'Midfielder','MID','Midfielders',2,5,5,?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,is_current,is_next,"
        "average_entry_score,highest_score,updated_at) VALUES (1,'GW1','2026-08-21T17:30:00Z',1,0,0,0,1,NULL,NULL,?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO fixtures (id,code,event,kickoff_time,team_h,team_a,team_h_score,team_a_score,"
        "team_h_difficulty,team_a_difficulty,finished,started,updated_at) "
        "VALUES (1,1,1,'2026-08-21T19:00:00Z',1,2,NULL,NULL,2,4,0,0,?)",
        (now,),
    )
    for pid, name, team_id in ((1, "Best", 1), (2, "Safe", 1), (3, "Punt", 2)):
        conn.execute(
            "INSERT INTO players (id,code,web_name,team_id,element_type,status,removed,updated_at) "
            "VALUES (?,?,?,?,1,'a',0,?)",
            (pid, pid, name, team_id, now),
        )
    conn.commit()


def _patch(monkeypatch):
    monkeypatch.setattr(captaincy_mod, "expected_points", lambda conn, pid, n_gw=1: _EP[pid])


def test_captaincy_report_picks_best_by_median(db_conn, monkeypatch):
    _seed(db_conn)
    _patch(monkeypatch)

    report = captaincy_mod.captaincy_report(db_conn, [1, 2, 3])

    assert report.best.player_id == 1  # highest median (6.0)
    assert report.second.player_id == 2  # second-highest median (5.0)


def test_captaincy_report_safe_and_high_upside_can_differ_from_best(db_conn, monkeypatch):
    _seed(db_conn)
    _patch(monkeypatch)

    report = captaincy_mod.captaincy_report(db_conn, [1, 2, 3])

    assert report.safe.player_id == 2      # highest floor (4.0)
    assert report.high_upside.player_id == 3  # highest ceiling (12.0)


def test_captaincy_report_flags_low_confidence_and_rotation_risk(db_conn, monkeypatch):
    _seed(db_conn)
    _patch(monkeypatch)

    report = captaincy_mod.captaincy_report(db_conn, [1, 2, 3])

    risk_text = " ".join(report.risks)
    assert "Punt" in risk_text  # LOW confidence and <75 expected minutes


def test_captaincy_report_flags_real_differential_captain(db_conn, monkeypatch):
    _seed(db_conn)
    _patch(monkeypatch)

    # Best (player 1) has 40% raw ownership but only 12% effective ownership -
    # the field owns it but rarely captains it, a real rank-differential armband.
    db_conn.execute(
        "INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) "
        "VALUES (1, 40.0, 't0', NULL)"
    )
    db_conn.execute(
        "INSERT INTO player_sample_ownership_history "
        "(player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
        "VALUES (1, 1, 100, 40, 12, 12, 24, 't0')"  # eo_percent = 12.0
    )
    db_conn.commit()

    report = captaincy_mod.captaincy_report(db_conn, [1, 2, 3])

    assert report.best.player_id == 1  # unchanged - still highest median
    assert report.best.eo_source == "sampled"
    assert report.best.effective_ownership_percent == 12.0
    assert report.differential_captain_note is not None
    assert "Best" in report.differential_captain_note  # web_name of player 1


def test_captaincy_report_no_note_without_eo_sample(db_conn, monkeypatch):
    _seed(db_conn)
    _patch(monkeypatch)

    report = captaincy_mod.captaincy_report(db_conn, [1, 2, 3])

    assert report.differential_captain_note is None
    assert report.best.eo_source == "unavailable"


def test_captaincy_player_absent_from_the_sample_is_unavailable_not_a_fabricated_zero(db_conn, monkeypatch):
    """A sample exists, but the best pick was never measured in it. Reporting that as a
    0.0% sampled EO would fire differential_captain_note off a number nobody measured."""
    _seed(db_conn)
    _patch(monkeypatch)

    db_conn.execute(
        "INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) "
        "VALUES (1, 40.0, 't0', NULL)"
    )
    db_conn.execute(  # only player 3 appears in the sample; player 1 (the best pick) doesn't
        "INSERT INTO player_sample_ownership_history "
        "(player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
        "VALUES (3, 1, 100, 40, 12, 12, 24, 't0')"
    )
    db_conn.commit()

    report = captaincy_mod.captaincy_report(db_conn, [1, 2, 3])

    assert report.best.player_id == 1
    assert report.best.eo_source == "unavailable"
    assert report.best.effective_ownership_percent is None
    assert report.differential_captain_note is None
