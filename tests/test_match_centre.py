"""Real coverage for `monitoring/dashboard/match_centre.py` (2026-08-29
forensic product redesign pass) - this module previously had zero direct
test coverage of its own; the cap-removal and analysis-merge changes made
this pass are real behavior changes that need real proof, not just a
visual screenshot check."""
from fpl_agent.ingestion.analysis_queue import enqueue_analysis_job
from fpl_agent.monitoring.dashboard.legacy import _match_feed_html
from fpl_agent.monitoring.dashboard.match_centre import (
    _match_analysis_html,
    _momentum_chart_html,
    _shot_map_svg,
    render_match_centre,
)


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


def _momentum_payload(result: str) -> dict:
    import html
    import json
    import re
    m = re.search(r"data-chart=\"([^\"]*)\"", result)
    assert m is not None, f"no data-chart payload found in {result!r}"
    return json.loads(html.unescape(m.group(1)))


def test_momentum_chart_marks_real_goal_events_and_half_time(db_conn):
    """Real product-redesign requirement: momentum must show "half-time
    divider... goals... major events", not just an unlabelled area chart.
    A goal event already stored in `match_events` (the same table the
    Match Feed reads) becomes a real annotation at its own real minute,
    attributed to the real scoring side; `halftime` is true whenever the
    match has reached minute 45, regardless of whether a goal happened at
    that exact minute (2026-08-29 ApexCharts rewrite - the client-side
    plugin draws these from this same real, server-computed payload)."""
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

    result = _momentum_chart_html(db_conn, match_id, momentum, home_team_id=1)

    payload = _momentum_payload(result)
    assert payload["halftime"] is True
    assert len(payload["goals"]) == 1
    assert payload["goals"][0]["minute"] == 23
    assert payload["goals"][0]["side"] == "home"


def test_momentum_chart_splits_signed_pressure_into_real_home_away_series(db_conn):
    """Real, deterministic transform check - `home`/`away` series are just
    `max(v,0)`/`min(v,0)` of the SAME one real signed value per minute, not
    a second data source. Never invents a value the real FotMob sample
    didn't report."""
    _insert_team(db_conn, 1, "AAA")
    _insert_team(db_conn, 2, "BBB")
    _insert_live_match(db_conn, "600006", 1, 2)
    db_conn.commit()
    match_id = db_conn.execute("SELECT id FROM match_intelligence").fetchone()["id"]
    momentum = [{"minute": 0, "value": 10}, {"minute": 21, "value": -20}]

    result = _momentum_chart_html(db_conn, match_id, momentum, home_team_id=1)

    payload = _momentum_payload(result)
    assert payload["minutes"] == [0, 21]
    assert payload["home"] == [10, 0]
    assert payload["away"] == [0, -20]
    assert payload["maxMinute"] == 21


def test_shot_map_clamps_a_real_out_of_range_coordinate_onto_the_pitch(db_conn):
    """Real bug found live (2026-08-29, direct user report): FotMob's own
    real x/y occasionally lands slightly outside the nominal 0-100 range
    (confirmed live: a real away-team shot at x=102.8) - mirrored via
    `100 - x` for an away shot this goes negative, drawing the dot off the
    pitch rect entirely, clipped by the SVG viewBox - a real shot silently
    invisible rather than shown at the true edge."""
    shots = [
        {"minute": 11, "x": 102.8, "y": 40.0, "xg": 0.5, "outcome": "Miss", "team_id": 2, "player_name": "P"},
    ]

    result = _shot_map_svg(1, shots, home_team_id=1, home_short="AAA", away_short="BBB")

    import re
    m = re.search(r"<circle cx='(-?[\d.]+)'", result)
    assert m is not None
    assert float(m.group(1)) >= 0.0  # never negative - the real shot stays on the visible pitch


def test_match_feed_strips_the_real_redundant_leading_word_from_description(db_conn):
    """Real bug found live (2026-08-29, direct user report: "the live
    football dashboard looks a little off") - a genuinely live match's own
    match feed showed "GOAL Goal — Dan Ndoye" / "SHOT Shot saved — Xaver
    Schlager": FotMob's own real description text already restates the
    event type as its own leading word, duplicating the colored type
    badge shown right next to it. The STORED description must stay exactly
    as FotMob supplied it (never mutated in the DB) - only this render
    trims the one duplicated word."""
    conn = db_conn
    _insert_team(conn, 1, "AAA")
    conn.execute(
        "INSERT INTO match_intelligence (fotmob_match_id, home_team_id, away_team_id, status, "
        "home_score, away_score, retrieved_at) VALUES ('700001', 1, 1, 'LIVE', 0, 1, 't0')"
    )
    match_id = conn.execute("SELECT id FROM match_intelligence WHERE fotmob_match_id='700001'").fetchone()["id"]
    conn.execute(
        "INSERT INTO match_events (match_id, source, source_event_id, minute, event_type, team_id, "
        "description, retrieved_at) VALUES (?, 'fotmob', 'g1', 24, 'Goal', 1, "
        "'Goal \u2014 Dan Ndoye (assist by Morgan Gibbs-White)', 't1')",
        (match_id,),
    )
    conn.commit()

    result = _match_feed_html(conn, match_id)

    assert "Goal Goal" not in result
    assert "Dan Ndoye" in result
    assert "match-feed-type-goal'>Goal<" in result


def test_match_feed_keeps_the_real_description_when_stripping_would_leave_it_blank(db_conn):
    """Real edge case found live (2026-08-29): a genuine FotMob "VAR" event
    had a description of just "VAR \u2014 " with nothing after the dash -
    stripping the redundant leading word would leave a blank description
    next to a badge with no other content. Never let a real event go
    silently blank just to avoid a duplicated word."""
    conn = db_conn
    _insert_team(conn, 1, "AAA")
    conn.execute(
        "INSERT INTO match_intelligence (fotmob_match_id, home_team_id, away_team_id, status, "
        "home_score, away_score, retrieved_at) VALUES ('700002', 1, 1, 'LIVE', 0, 0, 't0')"
    )
    match_id = conn.execute("SELECT id FROM match_intelligence WHERE fotmob_match_id='700002'").fetchone()["id"]
    conn.execute(
        "INSERT INTO match_events (match_id, source, source_event_id, minute, event_type, team_id, "
        "description, retrieved_at) VALUES (?, 'fotmob', 'v1', 60, 'VAR', 1, 'VAR \u2014 ', 't1')",
        (match_id,),
    )
    conn.commit()

    result = _match_feed_html(conn, match_id)

    assert "match-feed-desc'>VAR" in result  # kept the real description rather than going blank
