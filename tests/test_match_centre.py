"""Real coverage for `monitoring/dashboard/match_centre.py` (2026-08-29
forensic product redesign pass) - this module previously had zero direct
test coverage of its own; the cap-removal and analysis-merge changes made
this pass are real behavior changes that need real proof, not just a
visual screenshot check."""
from fpl_agent.ingestion.analysis_queue import enqueue_analysis_job
from fpl_agent.monitoring.dashboard.match_centre import _match_analysis_html, _momentum_svg, render_match_centre


def _insert_team(conn, team_id, short_name):
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, strength_overall_home, strength_overall_away, "
        "strength_attack_home, strength_attack_away, strength_defence_home, strength_defence_away, "
        "pulse_id, updated_at) VALUES (?,?,?,?,3,3,0,0,0,0,?,'t0')",
        (team_id, team_id, f"Team{team_id}", short_name, team_id),
    )


def _insert_live_match(conn, fotmob_id, home_id, away_id, status="LIVE"):
    conn.execute(
        "INSERT INTO match_intelligence "
        "(fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, "
        "home_score, away_score, live_minute, source, retrieved_at, confidence) "
        "VALUES (?,'Premier League','2026-08-29T14:00:00.000Z',?,?,?,1,0,'55','fotmob',"
        "'2026-08-29T14:55:00+00:00','high')",
        (fotmob_id, home_id, away_id, status),
    )


def test_render_match_centre_shows_more_than_three_concurrent_live_matches(db_conn):
    """Real product-redesign requirement: "at least 3+ simultaneous live
    matches must look coherent" - a genuine full-slate kickoff (up to 10
    PL fixtures at once) must not be silently truncated. Seeds 4 real LIVE
    matches (8 real teams) and confirms all 4 render, not just the first 3
    the old `matches[:3]` cap would have kept."""
    for i in range(8):
        _insert_team(db_conn, i + 1, f"T{i + 1}")
    for i in range(4):
        _insert_live_match(db_conn, f"55000{i}", i * 2 + 1, i * 2 + 2)
    db_conn.commit()

    result = render_match_centre(db_conn, frozenset())

    assert result.count('data-match-card="') == 4
    for i in range(4):
        assert f"55000{i}" in result


def test_match_analysis_html_empty_when_nothing_real_exists(db_conn):
    """No fabrication: a live match with no real analysis summary and no
    real queued job renders nothing for this section, never a placeholder
    like "not yet analyzed"."""
    _insert_team(db_conn, 1, "AAA")
    _insert_team(db_conn, 2, "BBB")
    _insert_live_match(db_conn, "600001", 1, 2)
    db_conn.commit()
    match_id = db_conn.execute("SELECT id FROM match_intelligence").fetchone()["id"]

    assert _match_analysis_html(db_conn, match_id) == ""


def test_match_analysis_html_shows_provisional_headline_for_halftime_match(db_conn):
    """The real case that used to leak through the retired standalone
    "Match Intelligence" panel as a SECOND representation of the same
    match - now the single, correct home for a HALFTIME match's real
    provisional headline."""
    _insert_team(db_conn, 1, "AAA")
    _insert_team(db_conn, 2, "BBB")
    _insert_live_match(db_conn, "600002", 1, 2, status="HALFTIME")
    db_conn.commit()
    match_id = db_conn.execute("SELECT id FROM match_intelligence").fetchone()["id"]
    db_conn.execute(
        "INSERT INTO match_analysis_summary (match_id, phase, headline, uncertainties, analysis_version, generated_at) "
        "VALUES (?, 'HALFTIME', 'Home side ahead at the break', 'small sample', 'qual-v1', '2026-08-29T14:50:05+00:00')",
        (match_id,),
    )
    db_conn.commit()

    result = _match_analysis_html(db_conn, match_id)

    assert "PROVISIONAL" in result
    assert "Home side ahead at the break" in result


def test_match_analysis_html_shows_pending_job_state(db_conn):
    _insert_team(db_conn, 1, "AAA")
    _insert_team(db_conn, 2, "BBB")
    _insert_live_match(db_conn, "600003", 1, 2)
    db_conn.commit()
    match_id = db_conn.execute("SELECT id FROM match_intelligence").fetchone()["id"]
    enqueue_analysis_job(db_conn, match_id, "HALFTIME", "Team A 1-0 Team B (halftime)")

    result = _match_analysis_html(db_conn, match_id)

    assert "QUALITATIVE ANALYSIS" in result
    assert "PENDING" in result


def test_render_match_centre_folds_analysis_into_the_same_card_not_a_second_panel(db_conn):
    """Real merge check: the qualitative headline for a live match now
    appears WITHIN that match's own Live Football card, not in a separate
    section of the page."""
    _insert_team(db_conn, 1, "AAA")
    _insert_team(db_conn, 2, "BBB")
    _insert_live_match(db_conn, "600004", 1, 2, status="HALFTIME")
    db_conn.commit()
    match_id = db_conn.execute("SELECT id FROM match_intelligence").fetchone()["id"]
    db_conn.execute(
        "INSERT INTO match_analysis_summary (match_id, phase, headline, uncertainties, analysis_version, generated_at) "
        "VALUES (?, 'HALFTIME', 'A real tactical headline', NULL, 'qual-v1', '2026-08-29T14:50:05+00:00')",
        (match_id,),
    )
    db_conn.commit()

    result = render_match_centre(db_conn, frozenset())

    assert "A real tactical headline" in result
    assert result.count('data-match-card="') == 1


def test_momentum_svg_marks_real_goal_events_and_half_time(db_conn):
    """Real product-redesign requirement: momentum must show "half-time
    divider... goals... major events", not just an unlabelled area chart.
    A goal event already stored in `match_events` (the same table the
    Match Feed reads) gets a real marker at its own real minute, coloured
    by the real scoring team; 45' gets the distinct half-time divider
    class regardless of whether a goal happened at that exact minute."""
    _insert_team(db_conn, 1, "AAA")
    _insert_team(db_conn, 2, "BBB")
    _insert_live_match(db_conn, "600005", 1, 2)
    db_conn.commit()
    match_id = db_conn.execute("SELECT id FROM match_intelligence").fetchone()["id"]
    db_conn.execute(
        "INSERT INTO match_events (match_id, source, source_event_id, minute, event_type, team_id, "
        "description, retrieved_at) VALUES (?, 'fotmob', 'g1', 23, 'Goal', 1, 'Goal - Scorer', 't1')",
        (match_id,),
    )
    db_conn.commit()
    momentum = [{"minute": 0, "value": 10}, {"minute": 23, "value": 40}, {"minute": 50, "value": -5}]

    result = _momentum_svg(db_conn, match_id, momentum, home_team_id=1)

    assert "match-momentum-goal-home" in result
    assert "match-momentum-ht" in result
