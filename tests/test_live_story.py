"""A live match is read as a provisional story; an early starter withdrawal is called an injury at the measured rate."""
from fpl_agent.models.match_analyst import analyse_live, build_story, parse_live_minute, store_story, truncate_inputs
from fpl_agent.models.signal_reliability import suspect_probability, suspect_rates

HOME, AWAY = 5, 8


def _seed(conn):
    conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (3, 'Midfielder', 'MID', 'Midfielders', 't0')")
    for tid in (HOME, AWAY):
        conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (?, ?, ?, ?, 't0')", (tid, tid, f"T{tid}", f"T{tid}"))
    for pid in range(1, 12):
        conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (?, ?, ?, ?, 3, 'a', 0, 't0')", (pid, pid, f"P{pid}", HOME))
    for mid in range(1, 9):
        conn.execute(
            "INSERT INTO match_intelligence (id, fotmob_match_id, status, home_team_id, away_team_id, home_score, away_score, kickoff_utc, source, retrieved_at) "
            "VALUES (?, ?, ?, ?, ?, 0, 0, '2026-09-01T12:00:00.000Z', 'fotmob', 't0')", (mid, f"f{mid}", "LIVE" if mid == 8 else "FULL_TIME", HOME, AWAY),
        )
    for mid in range(1, 8):
        subs = [{"kind": "INJURY_LINKED", "team_id": HOME, "off_id": 1, "minute": 20}]
        subs += [{"kind": "LIKE_FOR_LIKE", "team_id": HOME, "off_id": 2, "minute": 70}] * 3
        store_story(conn, {"version": "analyst-v1", "match_id": mid, "findings": [], "subs": subs})
        for pid in (1, 2):
            conn.execute("INSERT INTO player_match_state (match_id, player_id, team_id, started, minutes, source, retrieved_at) VALUES (?, ?, ?, 1, 60, 'fotmob', 't0')", (mid, pid, HOME))
    for pid, started in ((1, 1), (2, 1), (3, 0)):
        conn.execute("INSERT INTO player_match_state (match_id, player_id, team_id, started, minutes, source, retrieved_at) VALUES (8, ?, ?, ?, 20, 'fotmob', 't0')", (pid, HOME, started))
    conn.commit()


def test_rates_call_every_early_withdrawal_and_almost_no_late_one(db_conn):
    _seed(db_conn)
    rates = suspect_rates(db_conn)
    assert rates["35 or earlier"]["n"] == 7 and rates["35 or earlier"]["injury"] == 7 and rates["35 or earlier"]["rate"] > 0.9
    assert rates["61-75"]["injury"] == 0 and rates["61-75"]["rate"] < 0.1
    assert suspect_probability(rates, 20)["rate"] > 0.5 and suspect_probability(rates, 70)["rate"] < 0.5


def test_live_minute_parsing():
    assert parse_live_minute("56'") == 56 and parse_live_minute("45+2'") == 45 and parse_live_minute("HT") == 45
    assert parse_live_minute(None) is None and parse_live_minute("") is None


def _inputs(shots, events, score=(0, 0)):
    players = {
        1: {"web_name": "A", "second_name": "A", "first_name": "A", "team_id": HOME, "position": "MID", "status": "a", "news": None, "news_added": None},
        2: {"web_name": "B", "second_name": "B", "first_name": "B", "team_id": AWAY, "position": "MID", "status": "a", "news": None, "news_added": None},
    }
    return {
        "match": {"id": 8, "kickoff": "2026-09-01T12:00:00.000Z", "home_id": HOME, "away_id": AWAY, "home_name": "H", "away_name": "A", "home_score": score[0], "away_score": score[1]},
        "shots": shots, "events": events, "pms": [], "players": players,
    }


def test_replaying_a_match_to_a_minute_keeps_only_what_had_happened_and_marks_it_provisional():
    def shot(m, team, xg, outcome="AttemptSaved"):
        return {"minute": m, "team_id": team, "player_id": 1, "player_name": "A", "x": 94.0, "y": 34.0, "xg": xg, "xgot": xg, "on_target": True,
                "outcome": outcome, "situation": "RegularPlay", "shot_type": "RightFoot"}

    full = _inputs(
        [shot(10, HOME, 0.4, "Goal"), shot(60, AWAY, 0.5, "Goal"), shot(80, HOME, 0.3)],
        [{"id": 1, "minute": 10, "type": "Goal", "team_id": HOME, "player_id": 1, "description": "Goal - A"},
         {"id": 2, "minute": 60, "type": "Goal", "team_id": AWAY, "player_id": 2, "description": "Goal - B"}],
        score=(1, 1),
    )
    cut = truncate_inputs(full, 30)
    assert len(cut["shots"]) == 1 and cut["match"]["home_score"] == 1 and cut["match"]["away_score"] == 0
    story = build_story(cut, None, live_minute=30)
    assert story["provisional"] is True and story["length"] == 30 and story["headline"].startswith("Minute 30")
    assert story["state_profile"]["home"]["leading"]["minutes"] == 20
    assert not any("deserved from the shots" in f["observed"] for f in story["findings"])


def test_an_early_starter_withdrawal_in_a_live_story_becomes_a_suspect_finding(db_conn):
    _seed(db_conn)
    inputs = _inputs([], [{"id": 1, "minute": 20, "type": "Substitution", "team_id": HOME, "player_id": 3, "description": "P3 on for P1"}])
    inputs["pms"] = [
        {"player_id": 1, "team_id": HOME, "started": 1, "minutes": 20, "on_min": None, "off_min": 20, "goals": 0, "assists": 0, "xa": 0, "rating": None},
        {"player_id": 3, "team_id": HOME, "started": 0, "minutes": 70, "on_min": 20, "off_min": None, "goals": 0, "assists": 0, "xa": 0, "rating": None},
    ]
    inputs["players"] = {pid: {"web_name": f"P{pid}", "second_name": f"P{pid}", "first_name": "x", "team_id": HOME, "position": "MID", "status": "a", "news": None, "news_added": None} for pid in (1, 3)}
    inputs["suspect_rates"] = suspect_rates(db_conn)
    story = build_story(inputs, None, live_minute=25)
    assert story["subs"][0]["kind"] == "INJURY_SUSPECT"
    flag = [f for f in story["findings"] if f["subject_id"] == 1]
    assert flag and flag[0]["fpl_direction"] == "NEGATIVE" and "7 of 7" in flag[0]["observed"]
    assert analyse_live(db_conn, 1) is None


def test_the_early_withdrawal_detector_quotes_the_measured_rate(db_conn):
    from fpl_agent.ingestion.change_detection import detect_early_withdrawals

    _seed(db_conn)
    db_conn.execute("UPDATE player_match_state SET substituted_off_minute = 20 WHERE match_id = 8 AND player_id = 1")
    db_conn.commit()
    assert detect_early_withdrawals(db_conn, {1}, match_id=8, now="t1") == 1
    row = db_conn.execute("SELECT severity, fpl_impact FROM change_events WHERE event_type = 'early_withdrawal'").fetchone()
    assert row["severity"] == "HIGH" and "7 of 7 starters taken off that early" in row["fpl_impact"]
