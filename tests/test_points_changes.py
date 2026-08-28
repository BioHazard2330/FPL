from fpl_agent.models.points_changes import detect_points_revisions


def _seed_base(conn):
    now = "t0"
    conn.execute(
        "INSERT INTO teams (id,code,name,short_name,strength_overall_home,strength_overall_away,"
        "strength_attack_home,strength_attack_away,strength_defence_home,strength_defence_away,pulse_id,updated_at) "
        "VALUES (1,1,'T1','T1',3,3,0,0,0,0,1,?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO teams (id,code,name,short_name,strength_overall_home,strength_overall_away,"
        "strength_attack_home,strength_attack_away,strength_defence_home,strength_defence_away,pulse_id,updated_at) "
        "VALUES (2,2,'T2','T2',3,3,0,0,0,0,2,?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO element_types (id,singular_name,singular_name_short,plural_name,squad_min_play,"
        "squad_max_play,squad_select,updated_at) VALUES (2,'Defender','DEF','Defenders',3,5,5,?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO players (id,code,web_name,team_id,element_type,status,removed,updated_at) "
        "VALUES (1,1,'D1',1,2,'a',0,?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (1,'GW1','2026-08-21T17:30:00Z',0,1,0,0,0,'t0')"
    )
    conn.execute(
        "INSERT INTO fixtures (id,code,event,kickoff_time,team_h,team_a,team_h_score,team_a_score,"
        "finished,started,updated_at) VALUES (1,1,1,'2026-08-21T19:00:00Z',1,2,1,0,1,1,?)",
        (now,),
    )
    conn.commit()


def _snap(conn, player_id, retrieved_at, bonus, defcon):
    conn.execute(
        "INSERT INTO player_stats_snapshot (player_id, retrieved_at, stats_hash, bonus, defensive_contribution) "
        "VALUES (?,?,?,?,?)",
        (player_id, retrieved_at, retrieved_at, bonus, defcon),
    )


def test_no_revision_when_post_match_value_is_stable(db_conn):
    _seed_base(db_conn)
    # Full time ~21:10 + 30min buffer = 21:40. Both post-cutoff snapshots agree (bonus=2).
    _snap(db_conn, 1, "2026-08-21T18:00:00Z", 0, 0)
    _snap(db_conn, 1, "2026-08-21T21:45:00Z", 2, 5)
    _snap(db_conn, 1, "2026-08-22T08:00:00Z", 2, 5)
    db_conn.commit()

    result = detect_points_revisions(db_conn, event=1)

    assert result == []


def test_real_defcon_revision_detected_after_full_time(db_conn):
    _seed_base(db_conn)
    _snap(db_conn, 1, "2026-08-21T21:45:00Z", 2, 5)
    _snap(db_conn, 1, "2026-08-25T08:00:00Z", 2, 6)  # DefCon corrected 5 -> 6, days later
    db_conn.commit()

    result = detect_points_revisions(db_conn, event=1)

    assert len(result) == 1
    rev = result[0]
    assert rev.category == "defcon"
    assert rev.old_value == 5 and rev.new_value == 6
    assert rev.player_id == 1
    # DEF threshold is 10 - neither 5 nor 6 crosses it, so zero real points impact.
    assert rev.old_points == 0 and rev.new_points == 0


def test_bonus_revision_carries_real_points_impact(db_conn):
    _seed_base(db_conn)
    _snap(db_conn, 1, "2026-08-21T21:45:00Z", 1, 0)
    _snap(db_conn, 1, "2026-08-22T09:00:00Z", 3, 0)  # bonus corrected 1 -> 3
    db_conn.commit()

    result = detect_points_revisions(db_conn, event=1)

    assert len(result) == 1
    rev = result[0]
    assert rev.category == "bonus"
    assert rev.old_value == 1 and rev.new_value == 3
    assert rev.old_points == 1 and rev.new_points == 3


def test_ignores_snapshots_within_the_revision_gap_window(db_conn):
    _seed_base(db_conn)
    # Both post-cutoff snapshots only 1 hour apart - real live-BPS settling
    # tail, not a genuine post-review revision (gap below the 2h bar).
    _snap(db_conn, 1, "2026-08-21T21:45:00Z", 1, 0)
    _snap(db_conn, 1, "2026-08-21T22:45:00Z", 2, 0)
    db_conn.commit()

    result = detect_points_revisions(db_conn, event=1)

    assert result == []


def test_returns_empty_when_no_finished_event(db_conn):
    result = detect_points_revisions(db_conn)

    assert result == []
