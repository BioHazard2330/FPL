"""The Match Analyst reads a finished match from its shots, goals and substitutions.
Every test here builds the inputs by hand so the expected reading is known
before the engine runs: a score timeline with an own goal, a 3-0 first quarter
of an hour built on low-xG shots, a dead-ball-heavy side, a team with three
injury-linked substitutions, and a late chase of headers."""
import json

import pytest

from fpl_agent.ingestion.qualitative_analysis import _validate_payload
from fpl_agent.models.match_analyst import (
    best_spell,
    build_story,
    dedupe_events,
    draft_payload,
    load_story,
    situation_group,
    state_profile,
    store_story,
    zone,
)

HOME, AWAY = 5, 8


def _shot(minute, team, pid, xg, situation="RegularPlay", outcome="AttemptSaved", shot_type="RightFoot", x=92.0, y=34.0, on_target=True, name="x"):
    return {"minute": minute, "team_id": team, "player_id": pid, "player_name": name, "x": x, "y": y, "xg": xg,
            "xgot": xg if on_target else None, "on_target": on_target, "outcome": outcome, "situation": situation, "shot_type": shot_type}


def _event(minute, etype, team, pid=None, description="", eid=None):
    return {"id": eid or minute * 10, "minute": minute, "type": etype, "team_id": team, "player_id": pid, "description": description}


def _players():
    out = {}
    for pid, team, pos, name in [
        (1, HOME, "FWD", "Striker"), (2, HOME, "MID", "Mid"), (3, HOME, "DEF", "Centre"), (4, HOME, "DEF", "Back"),
        (11, AWAY, "FWD", "Forward"), (12, AWAY, "MID", "Engine"), (13, AWAY, "DEF", "Stopper"), (14, AWAY, "MID", "Sub"),
    ]:
        out[pid] = {"web_name": name, "second_name": name, "first_name": "A", "team_id": team, "position": pos,
                    "status": "a", "news": None, "news_added": None}
    return out


def _pms(extra=None):
    rows = [
        {"player_id": 1, "team_id": HOME, "started": 1, "minutes": 71, "on_min": None, "off_min": 71, "goals": 1, "assists": 0, "xa": 0.1, "rating": 7.5},
        {"player_id": 2, "team_id": HOME, "started": 1, "minutes": 90, "on_min": None, "off_min": None, "goals": 0, "assists": 1, "xa": 0.3, "rating": 7.0},
        {"player_id": 11, "team_id": AWAY, "started": 1, "minutes": 90, "on_min": None, "off_min": None, "goals": 0, "assists": 0, "xa": 0.0, "rating": 6.0},
    ]
    return rows + (extra or [])


def _match(home_score, away_score):
    return {"id": 1, "kickoff": "2026-10-18T13:00:00.000Z", "home_id": HOME, "away_id": AWAY, "home_name": "Brighton", "away_name": "Palace",
            "home_score": home_score, "away_score": away_score}


def test_zone_uses_metres_on_a_105_by_68_pitch():
    assert zone(100.0, 34.0) == "six_yard"
    assert zone(92.0, 20.0) == "box"
    assert zone(92.0, 10.0) == "outside"
    assert zone(80.0, 34.0) == "outside"
    assert zone(None, 34.0) is None


def test_situation_groups():
    assert situation_group("FromCorner") == "dead_ball"
    assert situation_group("ThrowInSetPiece") == "dead_ball"
    assert situation_group("FastBreak") == "fast_break"
    assert situation_group("Penalty") == "penalty"
    assert situation_group("IndividualPlay") == "open_play"
    assert situation_group(None) == "open_play"


def test_duplicate_substitutions_a_minute_apart_count_once():
    events = [
        _event(71, "Substitution", HOME, 3, "Hinshelwood on for Gross", eid=1),
        _event(72, "Substitution", HOME, 3, "Hinshelwood on for Gross", eid=2),
        _event(75, "Substitution", HOME, 4, "Other on for Another", eid=3),
    ]
    kept, dropped = dedupe_events(events)
    assert dropped == 1 and [e["id"] for e in kept] == [1, 3]


def test_an_own_goal_is_credited_to_the_other_side_and_carries_no_shot():
    events = [_event(4, "Goal", HOME, 13, "Goal - Stopper")]
    inputs = {"match": _match(1, 0), "shots": [_shot(4, AWAY, 13, None, outcome="Goal", x=3.0)], "events": events,
              "pms": _pms(), "players": _players()}
    story = build_story(inputs)
    goal = story["timeline"][0]
    assert goal["side"] == "home" and goal["own_goal"] is True and goal["score"] == [1, 0]
    assert story["metrics"]["home"]["goals"] == 0 and story["metrics"]["home"]["own_goals_for"] == 1
    assert story["metrics"]["away"]["shots"] == 0
    assert any("own goal" in f["observed"] for f in story["findings"])


def test_state_profile_splits_minutes_and_chances_by_the_score_at_the_time():
    goals = [{"minute": 10, "side": "home", "player_id": 1, "own_goal": False, "penalty": False, "assist_id": None, "assist_name": None, "score": [1, 0]}]
    shots = [_shot(5, HOME, 1, 0.2), _shot(30, HOME, 1, 0.4), _shot(60, AWAY, 11, 0.5)]
    prof = state_profile(goals, shots, HOME, 90)
    home = prof["home"]
    assert home["level"]["minutes"] == 10 and home["leading"]["minutes"] == 80
    assert home["level"]["xg_for"] == pytest.approx(0.2) and home["leading"]["xg_for"] == pytest.approx(0.4)
    assert prof["away"]["trailing"]["xg_for"] == pytest.approx(0.5)
    assert prof["away"]["trailing"]["minutes"] == 80


def test_best_spell_finds_the_densest_ten_minutes():
    shots = [_shot(27, AWAY, 11, 0.2), _shot(33, AWAY, 11, 0.1), _shot(35, AWAY, 11, 0.33), _shot(80, AWAY, 11, 0.05)]
    spell = best_spell(shots, AWAY)
    assert spell["start"] <= 27 and spell["end"] >= 35
    assert spell["xg"] == pytest.approx(0.63) and spell["share"] == pytest.approx(0.63 / 0.68, abs=1e-3)
    assert spell["shots"] == 3


def test_dead_ball_dependence_is_reported_with_the_shot_share():
    shots = [_shot(10 + 8 * i, HOME, 3, 0.1, situation="FromCorner", shot_type="Header") for i in range(5)]
    shots += [_shot(30, HOME, 2, 0.04), _shot(50, HOME, 2, 0.03)]
    shots += [_shot(20, AWAY, 11, 0.05)]
    inputs = {"match": _match(0, 0), "shots": shots, "events": [], "pms": _pms(), "players": _players()}
    story = build_story(inputs, {"dead_ball_share": 0.24, "dead_ball_shares_sorted": [0.1, 0.2, 0.3, 0.4], "xg_totals_sorted": [], "team_matches": 4})
    texts = [f["observed"] for f in story["findings"] if f["subject_id"] == HOME and f["fpl_signal"] == "SET_PIECES"]
    assert texts and "5 of 7 shots" in texts[0] and "(88%)" in texts[0]


def test_one_big_rebound_does_not_make_a_side_set_piece_dependent():
    shots = [_shot(84, HOME, 2, 0.95, situation="FromCorner")] + [_shot(10 + 10 * i, HOME, 2, 0.06) for i in range(8)]
    inputs = {"match": _match(1, 0), "shots": shots, "events": [_event(84, "Goal", HOME, 2, "Goal - Mid")], "pms": _pms(), "players": _players()}
    story = build_story(inputs, {"dead_ball_share": 0.24, "dead_ball_shares_sorted": [0.1, 0.2, 0.3], "xg_totals_sorted": [], "team_matches": 3})
    assert not [f for f in story["findings"] if f["subject_id"] == HOME and f["fpl_signal"] == "SET_PIECES" and f["subject_type"] == "team"]


def test_injury_linked_substitutions_need_an_fpl_status_change_not_just_a_withdrawal():
    players = _players()
    events = [
        _event(46, "Substitution", AWAY, 14, "Sub on for Engine", eid=1),
        _event(60, "Substitution", AWAY, 13, "Stopper on for Forward", eid=2),
    ]
    pms = _pms([
        {"player_id": 12, "team_id": AWAY, "started": 1, "minutes": 45, "on_min": None, "off_min": 46, "goals": 0, "assists": 0, "xa": 0, "rating": 6.0},
        {"player_id": 14, "team_id": AWAY, "started": 0, "minutes": 44, "on_min": 46, "off_min": None, "goals": 0, "assists": 0, "xa": 0, "rating": 6.0},
    ])
    inputs = {"match": _match(0, 0), "shots": [], "events": events, "pms": pms, "players": players,
              "status_after": {12: {"status": "d", "detected_at": "2026-10-18T20:00:00+00:00", "news": "Thigh injury - 75% chance of playing"}}}
    story = build_story(inputs)
    kinds = {s["off"]: s["kind"] for s in story["subs"]}
    assert kinds["Engine"] == "INJURY_LINKED"
    injury = [f for f in story["findings"] if f["subject_id"] == 12]
    assert injury and injury[0]["fpl_direction"] == "NEGATIVE" and "Thigh injury" in injury[0]["observed"]


def test_without_a_status_change_a_half_time_swap_is_just_half_time():
    events = [_event(46, "Substitution", AWAY, 14, "Sub on for Engine", eid=1)]
    pms = _pms([{"player_id": 12, "team_id": AWAY, "started": 1, "minutes": 45, "on_min": None, "off_min": 46, "goals": 0, "assists": 0, "xa": 0, "rating": 6.0}])
    story = build_story({"match": _match(0, 0), "shots": [], "events": events, "pms": pms, "players": _players()})
    assert story["subs"][0]["kind"] == "HALF_TIME"


def test_three_injury_flags_from_one_side_become_one_team_finding():
    events = [
        _event(60, "Substitution", HOME, 2, "Mid on for Striker", eid=1),
        _event(70, "Substitution", HOME, 4, "Back on for Centre", eid=2),
    ]
    pms = _pms([
        {"player_id": 3, "team_id": HOME, "started": 1, "minutes": 70, "on_min": None, "off_min": 70, "goals": 0, "assists": 0, "xa": 0, "rating": 6.0},
    ])
    pms[0]["off_min"] = 60
    after = {pid: {"status": "d", "detected_at": "x", "news": None} for pid in (1, 3)}
    story = build_story({"match": _match(0, 0), "shots": [], "events": events, "pms": pms, "players": _players(), "status_after": after})
    team = [f for f in story["findings"] if f["subject_type"] == "team" and f["fpl_signal"] == "MINUTES"]
    assert team and "2 Brighton players" in team[0]["observed"]
    assert "flagged by FPL" in story["headline"]


def test_managed_minutes_when_two_goals_clear_late():
    goals = [_event(5, "Goal", HOME, 1, "Goal - Striker"), _event(20, "Goal", HOME, 2, "Goal - Mid")]
    events = goals + [_event(75, "Substitution", HOME, 4, "Back on for Striker", eid=9)]
    pms = _pms()
    story = build_story({"match": _match(2, 0), "shots": [_shot(5, HOME, 1, 0.3, outcome="Goal"), _shot(20, HOME, 2, 0.4, outcome="Goal")],
                         "events": events, "pms": pms, "players": _players()})
    sub = story["subs"][0]
    assert sub["kind"] == "MANAGED_MINUTES" and sub["margin"] == 2


def test_late_chase_of_headers_is_a_tactical_finding():
    shots = [_shot(62 + 5 * i, AWAY, 11, 0.05, shot_type="Header") for i in range(6)] + [_shot(20, AWAY, 11, 0.1)]
    events = [_event(10, "Goal", HOME, 1, "Goal - Striker"), _event(15, "Goal", HOME, 2, "Goal - Mid")]
    story = build_story({"match": _match(2, 0), "shots": shots, "events": events, "pms": _pms(), "players": _players()})
    chase = [f for f in story["findings"] if f["observation_type"] == "TACTICAL_CHANGE" and f["subject_id"] == AWAY]
    assert chase and "6 of Palace's 7 shots" not in chase[0]["observed"] and "6 of Palace's 6 shots from minute 60" in chase[0]["observed"]


def test_early_flurry_from_low_xg_shots_is_named():
    shots = [_shot(4, HOME, 1, 0.01, outcome="Goal"), _shot(7, HOME, 2, 0.05, outcome="Goal"), _shot(9, HOME, 2, 0.09, outcome="Goal")] + \
            [_shot(40 + 5 * i, HOME, 2, 0.1) for i in range(5)]
    events = [_event(4, "Goal", HOME, 1, "Goal - Striker"), _event(7, "Goal", HOME, 2, "Goal - Mid"), _event(9, "Goal", HOME, 2, "Goal - Mid")]
    story = build_story({"match": _match(3, 0), "shots": shots, "events": events, "pms": _pms(), "players": _players()})
    early = [f for f in story["findings"] if "goals by minute 9" in f["observed"]]
    assert early and "0.15 xG" in early[0]["observed"]


def test_a_timeline_that_misses_the_final_score_skips_game_state():
    story = build_story({"match": _match(2, 0), "shots": [_shot(5, HOME, 1, 0.3)], "events": [_event(5, "Goal", HOME, 1, "Goal - Striker")],
                         "pms": _pms(), "players": _players()})
    assert story["consistent"] is False and story["state_profile"] is None
    assert "does not add up" in story["uncertainties"]


def test_deserved_result_and_points_gap():
    shots = [_shot(10 * (i + 1), HOME, 1, 0.3) for i in range(6)]
    story = build_story({"match": _match(0, 1), "shots": shots + [_shot(80, AWAY, 11, 0.1, outcome="Goal")],
                         "events": [_event(80, "Goal", AWAY, 11, "Goal - Forward")], "pms": _pms(), "players": _players()})
    d = story["deserved"]
    assert d["actual_home_points"] == 0 and d["actual_away_points"] == 3
    assert d["home_win"] > d["away_win"]
    assert any(f["subject_id"] == AWAY and "deserved" in f["observed"] for f in story["findings"])


def test_penalty_taker_is_a_set_piece_finding():
    shots = [_shot(30, HOME, 1, 0.79, situation="Penalty", outcome="Goal", x=94.0)]
    events = [_event(30, "Goal", HOME, 1, "Goal - Striker")]
    story = build_story({"match": _match(1, 0), "shots": shots, "events": events, "pms": _pms(), "players": _players()})
    pen = [f for f in story["findings"] if f["fpl_signal"] == "SET_PIECES" and f["subject_type"] == "player"]
    assert pen and pen[0]["subject_id"] == 1 and "penalt" in pen[0]["observed"]
    assert story["timeline"][0]["penalty"] is True


def test_no_filler_words_in_any_finding():
    shots = [_shot(10 + 8 * i, HOME, 3, 0.1, situation="FromCorner", shot_type="Header") for i in range(5)] + [_shot(20, AWAY, 11, 0.9, outcome="Post")]
    story = build_story({"match": _match(0, 0), "shots": shots, "events": [], "pms": _pms(), "players": _players()})
    banned = ("genuine", "sustained", "trusted", "meaningful", "significant", "high-quality", "encouraging", "impressive")
    for f in story["findings"]:
        text = " ".join(str(f[k]) for k in ("observed", "inferred", "fpl_reason") if f[k]).lower()
        assert not any(w in text for w in banned), text
    assert not any(w in story["headline"].lower() for w in banned)


def test_the_draft_payload_passes_the_real_validator_and_drops_internal_fields():
    shots = [_shot(10 + 8 * i, HOME, 3, 0.1, situation="FromCorner", shot_type="Header") for i in range(5)] + [_shot(20, HOME, 2, 0.05)]
    story = build_story({"match": _match(0, 0), "shots": shots, "events": [], "pms": _pms(), "players": _players()},
                        {"dead_ball_share": 0.24, "dead_ball_shares_sorted": [0.1, 0.2, 0.3], "xg_totals_sorted": [], "team_matches": 3})
    payload = draft_payload(story)
    _validate_payload("FULL_TIME", payload)
    assert payload["observations"] and all("rank" not in o and "short" not in o for o in payload["observations"])
    json.dumps(story)


def test_story_round_trips_through_the_database(db_conn):
    db_conn.execute("INSERT INTO match_intelligence (id, fotmob_match_id, status, source, retrieved_at, home_score, away_score) VALUES (1, 'f1', 'FULL_TIME', 'fotmob', 't0', 0, 0)")
    story = build_story({"match": _match(0, 0), "shots": [_shot(10, HOME, 1, 0.2)], "events": [], "pms": _pms(), "players": _players()})
    store_story(db_conn, story)
    store_story(db_conn, story)
    back = load_story(db_conn, 1)
    assert back["headline"] == story["headline"]
    assert db_conn.execute("SELECT COUNT(*) FROM match_story").fetchone()[0] == 1


def _seed_story_rows(conn):
    from fpl_agent.models.match_analyst import store_story

    for tid in (HOME, AWAY):
        conn.execute("INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (?, ?, ?, ?, 't0')", (tid, tid, f"T{tid}", f"T{tid}"))
    for mid, kickoff, direction, subject in ((1, "2026-09-01T12:00:00Z", "POSITIVE", 1), (2, "2026-09-08T12:00:00Z", "NEGATIVE", 1), (3, "2026-09-08T12:00:00Z", "WATCH", 2)):
        conn.execute(
            "INSERT INTO match_intelligence (id, fotmob_match_id, status, home_team_id, away_team_id, home_score, away_score, kickoff_utc, source, retrieved_at) "
            "VALUES (?, ?, 'FULL_TIME', ?, ?, 1, 0, ?, 'fotmob', 't0')", (mid, f"f{mid}", HOME, AWAY, kickoff),
        )
        story = {"version": "analyst-v1", "match_id": mid, "findings": [{
            "subject_type": "player", "subject_id": subject, "name": f"P{subject}", "observation_type": "MINUTES", "observed": f"finding {mid}", "inferred": None,
            "fpl_direction": direction, "fpl_signal": "MINUTES", "confidence": "high", "reliability": None}]}
        store_story(conn, story)
    conn.commit()


def test_analyst_for_players_returns_each_players_latest_finding_most_worrying_first(db_conn):
    from fpl_agent.models.match_analyst import analyst_for_players

    _seed_story_rows(db_conn)
    notes = analyst_for_players(db_conn, {1, 2})
    assert [(n["player_id"], n["direction"], n["observed"]) for n in notes] == [(1, "NEGATIVE", "finding 2"), (2, "WATCH", "finding 3")]
    assert analyst_for_players(db_conn, set()) == []


def test_analyst_for_player_lists_matches_newest_first_and_skips_matches_without_him(db_conn):
    from fpl_agent.models.match_analyst import analyst_for_player

    _seed_story_rows(db_conn)
    rows = analyst_for_player(db_conn, 1)
    assert [r["match_id"] for r in rows] == [2, 1]
    assert rows[0]["findings"][0]["observed"] == "finding 2" and rows[0]["home"] == f"T{HOME}"
    assert [r["match_id"] for r in analyst_for_player(db_conn, 2)] == [3]


def test_a_recent_match_is_rebuilt_when_its_story_is_stale_but_an_old_one_is_not(db_conn):
    from datetime import datetime, timedelta, timezone

    from fpl_agent.models.match_analyst import ENGINE_VERSION, refresh_stories

    for tid in (HOME, AWAY):
        db_conn.execute("INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (?, ?, ?, ?, 't0')", (tid, tid, f"T{tid}", f"T{tid}"))
    now = datetime.now(timezone.utc)
    for mid, kickoff in ((1, now - timedelta(days=1)), (2, now - timedelta(days=20))):
        db_conn.execute(
            "INSERT INTO match_intelligence (id, fotmob_match_id, status, home_team_id, away_team_id, home_score, away_score, kickoff_utc, source, retrieved_at) "
            "VALUES (?, ?, 'FULL_TIME', ?, ?, 0, 0, ?, 'fotmob', 't0')", (mid, f"f{mid}", HOME, AWAY, kickoff.strftime("%Y-%m-%dT%H:%M:%S.000Z")),
        )
        db_conn.execute(
            "INSERT INTO match_story (match_id, engine_version, story_json, generated_at) VALUES (?, ?, '{}', ?)",
            (mid, ENGINE_VERSION, (now - timedelta(hours=2)).isoformat()),
        )
    db_conn.commit()
    assert refresh_stories(db_conn) == 1
    fresh = {r["match_id"]: r["generated_at"] for r in db_conn.execute("SELECT match_id, generated_at FROM match_story")}
    assert fresh[1] > (now - timedelta(minutes=5)).isoformat() and fresh[2] < (now - timedelta(hours=1)).isoformat()


def test_an_unreviewed_finished_match_gets_the_analysts_analysis_after_the_wait_and_a_reviewed_one_is_left_alone(db_conn):
    from datetime import datetime, timedelta, timezone

    from fpl_agent.models.match_analyst import auto_analyse_unreviewed, store_story

    for tid in (HOME, AWAY):
        db_conn.execute("INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (?, ?, ?, ?, 't0')", (tid, tid, f"T{tid}", f"T{tid}"))
    now = datetime.now(timezone.utc)
    shots = [_shot(10 + 8 * i, HOME, None, 0.1, situation="FromCorner", shot_type="Header") for i in range(5)] + [_shot(30, HOME, None, 0.04), _shot(50, HOME, None, 0.03)]
    for mid, hours_ago in ((1, 12), (2, 12), (3, 2)):
        db_conn.execute(
            "INSERT INTO match_intelligence (id, fotmob_match_id, status, home_team_id, away_team_id, home_score, away_score, kickoff_utc, source, retrieved_at) "
            "VALUES (?, ?, 'FULL_TIME', ?, ?, 0, 0, ?, 'fotmob', 't0')", (mid, f"f{mid}", HOME, AWAY, (now - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")),
        )
        story = build_story(
            {"match": {**_match(0, 0), "id": mid}, "shots": shots, "events": [], "pms": [], "players": {}},
            {"dead_ball_share": 0.24, "dead_ball_shares_sorted": [0.1, 0.2, 0.3], "xg_totals_sorted": [], "team_matches": 3},
        )
        story["match_id"] = mid
        store_story(db_conn, story)
    db_conn.execute("INSERT INTO match_analysis_summary (match_id, phase, headline, uncertainties, analysis_version, generated_at) VALUES (2, 'FULL_TIME', 'human', '', 'qual-v1', 't0')")
    db_conn.commit()

    assert auto_analyse_unreviewed(db_conn) == 1
    rows = db_conn.execute("SELECT match_id, analysis_version FROM match_analysis_summary ORDER BY match_id").fetchall()
    assert [(r["match_id"], r["analysis_version"]) for r in rows] == [(1, "analyst-v1"), (2, "qual-v1")]
    assert db_conn.execute("SELECT COUNT(*) FROM match_observations WHERE match_id = 1").fetchone()[0] > 0
    assert not db_conn.execute("SELECT 1 FROM match_observations WHERE match_id = 1 AND confidence = 'high'").fetchone()
    assert auto_analyse_unreviewed(db_conn) == 0
