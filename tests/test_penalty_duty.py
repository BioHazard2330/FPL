from fpl_agent.models.penalty_duty import league_penalty_evidence


def _seed_match_intelligence(conn, match_id):
    conn.execute("INSERT INTO teams (id,code,name,short_name,updated_at) VALUES (1,1,'T1','T1','t0')")
    conn.execute("INSERT INTO teams (id,code,name,short_name,updated_at) VALUES (2,2,'T2','T2','t0')")
    conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, home_team_id, away_team_id, status, retrieved_at) "
        "VALUES (?,?,1,2,'FULL_TIME','t0')",
        (match_id, f"fm{match_id}"),
    )
    conn.commit()


def test_league_penalty_evidence_is_real_and_honestly_insufficient_from_two_shots(db_conn):
    """The real GW1 state this project actually observed: 2 real penalty
    shots league-wide - genuinely, correctly insufficient to trust a rate
    from, not an arbitrary pessimistic default."""
    _seed_match_intelligence(db_conn, 1)
    db_conn.execute(
        "INSERT INTO player_match_state (match_id, fotmob_player_id, started, penalty_shots, penalty_goals, "
        "source, retrieved_at, confidence) VALUES (1,'p1',1,1,1,'fotmob','t0','medium')"
    )
    db_conn.execute(
        "INSERT INTO player_match_state (match_id, fotmob_player_id, started, penalty_shots, penalty_goals, "
        "source, retrieved_at, confidence) VALUES (1,'p2',1,1,0,'fotmob','t0','medium')"
    )
    db_conn.commit()

    evidence = league_penalty_evidence(db_conn)

    assert evidence.league_penalty_shots == 2
    assert evidence.league_penalty_goals == 1
    assert evidence.league_conversion_rate == 0.5
    assert evidence.sufficient_for_adjustment is False


def test_league_penalty_evidence_becomes_sufficient_once_real_volume_accumulates(db_conn):
    _seed_match_intelligence(db_conn, 1)
    for i in range(25):
        db_conn.execute(
            "INSERT INTO player_match_state (match_id, fotmob_player_id, started, penalty_shots, penalty_goals, "
            "source, retrieved_at, confidence) VALUES (1,?,1,1,1,'fotmob','t0','medium')",
            (f"p{i}",),
        )
    db_conn.commit()

    evidence = league_penalty_evidence(db_conn)

    assert evidence.league_penalty_shots == 25
    assert evidence.sufficient_for_adjustment is True


def test_league_penalty_evidence_honest_none_conversion_with_zero_shots(db_conn):
    evidence = league_penalty_evidence(db_conn)

    assert evidence.league_penalty_shots == 0
    assert evidence.league_conversion_rate is None
    assert evidence.sufficient_for_adjustment is False
