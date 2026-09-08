from types import SimpleNamespace

from fpl_agent.optimization import captaincy as captaincy_mod

_EP = {
    1: SimpleNamespace(position="MID", floor=3.0, median=6.0, ceiling=10.0, confidence="MEDIUM", expected_minutes=85.0, components=None),
    2: SimpleNamespace(position="DEF", floor=4.0, median=5.0, ceiling=9.0, confidence="HIGH", expected_minutes=90.0, components=None),
    3: SimpleNamespace(position="FWD", floor=1.0, median=3.0, ceiling=14.0, confidence="LOW", expected_minutes=45.0, components=None),
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
    monkeypatch.setattr(captaincy_mod, "expected_points", lambda conn, pid, n_gw=1, from_event=None: _EP[pid])


def test_captaincy_report_picks_best_by_median(db_conn, monkeypatch):
    _seed(db_conn)
    _patch(monkeypatch)

    report = captaincy_mod.captaincy_report(db_conn, [1, 2, 3])

    assert report.best.player_id == 1  # highest median (6.0)
    assert report.second.player_id == 2  # second-highest median (5.0)


def test_captaincy_report_options_carry_real_team_id(db_conn, monkeypatch):
    """Real regression (2026-09-08, art-direction pass v3, direct user
    follow-up: "more football") - `CaptainOption.team_id` is the same real
    `players.team_id` column already queried for `_next_opponent`, now also
    kept on the option itself so a JSON payload consumer can resolve a real
    shirt/crest without a second query or a fragile cross-reference into a
    different payload block."""
    _seed(db_conn)
    _patch(monkeypatch)

    options = captaincy_mod.evaluate_captaincy(db_conn, [1, 2, 3])

    by_id = {o.player_id: o for o in options}
    assert by_id[1].team_id == 1
    assert by_id[2].team_id == 1
    assert by_id[3].team_id == 2


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


def _opt(player_id, **components_kwargs):
    from fpl_agent.models.expected_points import ComponentBreakdown
    from fpl_agent.optimization.captaincy import CaptainOption

    defaults = dict(appearance=2.0, goals=0.0, assists=0.0, bonus=0.0, clean_sheet=0.0, cards=0.0, conceded=0.0, defcon=0.0)
    defaults.update(components_kwargs)
    return CaptainOption(
        player_id=player_id, web_name=f"P{player_id}", position="MID", floor=1.0, median=5.0, ceiling=10.0,
        confidence="HIGH", expected_minutes=90.0, is_penalty_taker=False, opponent_short="ARS", is_home=True,
        selected_by_percent=10.0, effective_ownership_percent=8.0, eo_source="sampled",
        components=ComponentBreakdown(**defaults),
    )


def test_captain_edge_driver_identifies_the_real_largest_component_gap():
    """Real, Phase 7.3 Part 13 ("why this captain, not merely N.N xP") - the
    single ComponentBreakdown field with the largest real difference between
    two players' own already-computed projections, not a fabricated
    additive decomposition."""
    current = _opt(1, goals=4.0, assists=0.5)  # a real goal-threat-driven projection
    alternative = _opt(2, goals=0.5, assists=0.5)  # same appearance/assists, much lower goal threat

    driver = captaincy_mod.captain_edge_driver(current, alternative)

    assert driver == ("goal probability", 3.5)


def test_captain_edge_driver_none_when_components_are_unavailable():
    current = _opt(1)
    alternative = _opt(2)
    object.__setattr__(current, "components", None)

    assert captaincy_mod.captain_edge_driver(current, alternative) is None
