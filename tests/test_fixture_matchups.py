def test_team_form_reads_both_sides_of_every_finished_match(db_conn):
    from fpl_agent.models.fixture_matchups import team_form

    for tid in (1, 2):
        db_conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?, ?, ?, ?, 't0')", (tid, 900 + tid, f"T{tid}", f"T{tid}"))
    db_conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, status, home_team_id, away_team_id, home_score, away_score, kickoff_utc, source, retrieved_at) "
        "VALUES (1, 'f1', 'FULL_TIME', 1, 2, 2, 0, '2026-09-10T12:00:00Z', 'fotmob', 't0')"
    )
    for i, (team, xg) in enumerate(((1, 1.2), (1, 0.6), (2, 0.4))):
        db_conn.execute("INSERT INTO match_shots (match_id, fotmob_shot_id, team_id, xg, situation, source, retrieved_at) VALUES (1, ?, ?, ?, 'RegularPlay', 'fotmob', 't0')", (str(i), team, xg))
    db_conn.commit()
    form = team_form(db_conn)
    assert form[1]["xg_for"] == 1.8 and form[1]["xg_against"] == 0.4 and form[1]["clean_sheets"] == 1
    assert form[2]["conceded"] == 2 and form[2]["clean_sheets"] == 0
