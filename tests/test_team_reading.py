"""A club's last stories read together: numbers only, and a measured-not-to-persist signal is labelled as such."""
import json

from fpl_agent.models.team_reading import fixture_reading, matchup_statements, side_statements, team_reading


def _story(match_id, home, away, hxg, axg, hscore, ascore, h_dead=0.2, a_dead=0.2, subs=None, kickoff="2026-09-01"):
    def metrics(xg, xga, goals, conceded, dead_for, dead_against):
        return {
            "xg": xg, "xg_against": xga, "goals": goals, "goals_conceded_excl_og": conceded, "header_xg_share": 0.2,
            "xg_by_situation": {"dead_ball": xg * dead_for, "open_play": xg * (1 - dead_for), "fast_break": 0, "penalty": 0},
            "xga_by_situation": {"dead_ball": xga * dead_against, "open_play": xga * (1 - dead_against), "fast_break": 0, "penalty": 0},
        }
    return {
        "match_id": match_id, "match": {"home": {"team_id": home}, "away": {"team_id": away}},
        "metrics": {"home": metrics(hxg, axg, hscore, ascore, h_dead, a_dead), "away": metrics(axg, hxg, ascore, hscore, a_dead, h_dead)},
        "deserved": {"home_points": 1.5, "away_points": 1.5, "actual_home_points": 3 if hscore > ascore else 1 if hscore == ascore else 0,
                     "actual_away_points": 3 if ascore > hscore else 1 if hscore == ascore else 0},
        "state_profile": {"home": {"leading": {"minutes": 40}, "level": {"minutes": 30}, "trailing": {"minutes": 20}},
                          "away": {"leading": {"minutes": 20}, "level": {"minutes": 30}, "trailing": {"minutes": 40}}},
        "subs": subs or [],
    }


def _insert(conn, story, home, away, kickoff):
    for tid in (home, away):
        conn.execute("INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (?, ?, ?, ?, 't0')", (tid, tid, f"T{tid}", f"T{tid}"))
    mid = story["match_id"]
    conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, status, home_team_id, away_team_id, home_score, away_score, kickoff_utc, source, retrieved_at) "
        "VALUES (?, ?, 'FULL_TIME', ?, ?, 0, 0, ?, 'fotmob', 't0')", (mid, f"f{mid}", home, away, kickoff),
    )
    conn.execute("INSERT INTO match_story (match_id, engine_version, story_json, generated_at) VALUES (?, 'analyst-v1', ?, 't0')", (mid, json.dumps(story)))


def test_team_reading_averages_the_last_stories_from_the_clubs_own_side(db_conn):
    _insert(db_conn, _story(1, 1, 2, 2.0, 1.0, 3, 0), 1, 2, "2026-09-01")
    _insert(db_conn, _story(2, 3, 1, 0.5, 1.5, 0, 1), 3, 1, "2026-09-08")
    db_conn.commit()
    r = team_reading(db_conn, 1)
    assert r["matches"] == 2
    assert r["xg"] == 1.75 and r["xga"] == 0.75
    assert r["goals"] == 4 and r["conceded"] == 0
    assert r["points"] == 6 and r["xpts"] == 3.0
    assert team_reading(db_conn, 99) is None


def test_results_far_ahead_of_the_chances_are_labelled_with_the_persistence_finding():
    r = {"matches": 5, "xg": 1.4, "xga": 1.1, "points": 13.0, "xpts": 8.0, "flagged": []}
    rel = {"metrics": {"goals_minus_xg": {"r": 0.03, "verdict": "none"}}}
    texts = [s["text"] for s in side_statements("MCI", r, {"xg": 1.5}, rel)]
    assert any("13 points from 8.0 deserved" in t and "has not carried" in t for t in texts)
    quiet = side_statements("MCI", {**r, "points": 8.5}, {"xg": 1.5}, rel)
    assert not any(s["kind"] == "luck" for s in quiet)


def test_two_dead_ball_sides_meeting_produce_one_set_piece_line_each_way_only_when_both_halves_hold():
    h = {"matches": 5, "xg": 1.5, "xga": 1.0, "dead_ball_share_for": 0.55, "dead_ball_share_against": 0.2}
    a = {"matches": 5, "xg": 1.2, "xga": 1.4, "dead_ball_share_for": 0.2, "dead_ball_share_against": 0.5}
    rel = {"metrics": {"dead_ball_xg_share": {"verdict": "unclear"}}}
    out = matchup_statements("LEE", "MUN", h, a, {"dead_ball_share": 0.24}, rel)
    assert [s["kind"] for s in out].count("set_pieces") == 1
    assert "LEE take 55%" in out[0]["text"] and "MUN concede 50%" in out[0]["text"]


def test_a_thin_sample_is_flagged_not_hidden(db_conn):
    _insert(db_conn, _story(1, 1, 2, 2.0, 1.0, 3, 0), 1, 2, "2026-09-01")
    db_conn.commit()
    out = fixture_reading(db_conn, 1, 2, "A", "B")
    assert out["statements"][0]["weight"] == "thin sample"
    assert fixture_reading(db_conn, 50, 51, "X", "Y") is None
