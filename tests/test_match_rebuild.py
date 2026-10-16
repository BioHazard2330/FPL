import numpy as np
import pytest

from fpl_agent.models.match_rebuild import deserved_result, goal_distribution, rebuild_match

from test_news_source_matching import _seed_two_players_two_teams


def test_goal_distribution_is_a_probability_distribution_with_the_right_mean():
    xgs = [0.8, 0.3, 0.05, 0.5]
    dist = goal_distribution(xgs)
    assert dist.sum() == pytest.approx(1.0)
    assert (dist * np.arange(len(dist))).sum() == pytest.approx(sum(xgs))
    assert dist[0] == pytest.approx(0.2 * 0.7 * 0.95 * 0.5)


def test_a_side_with_all_the_chances_deserves_to_win():
    r = deserved_result([0.5] * 6, [0.05] * 2)
    assert r["home_win"] > 0.8 and r["away_win"] < 0.05
    assert r["home_win"] + r["draw"] + r["away_win"] == pytest.approx(1.0)
    assert r["home_points"] == pytest.approx(3 * r["home_win"] + r["draw"])
    assert r["likely_score"][0] > r["likely_score"][1]


def test_equal_chances_give_equal_odds():
    r = deserved_result([0.3, 0.2], [0.3, 0.2])
    assert r["home_win"] == pytest.approx(r["away_win"])


def _match(db_conn, status="FULL_TIME"):
    db_conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, kickoff_utc, home_team_id, away_team_id, status, home_score, away_score, retrieved_at) "
        "VALUES (100, 'f1', '2026-10-10T15:00:00Z', 1, 2, ?, 3, 0, 't')", (status,),
    )
    shots = ((10, 1, 0.1, "Goal"), (30, 1, 0.05, "Miss"), (50, 2, 0.4, "AttemptSaved"), (70, 1, 0.2, "Goal"), (80, 1, 0.03, "Goal"))
    for n, (minute, team, xg, outcome) in enumerate(shots):
        db_conn.execute(
            "INSERT INTO match_shots (match_id, fotmob_shot_id, team_id, player_name, minute, xg, outcome, situation, retrieved_at) "
            "VALUES (100, ?, ?, 'P', ?, ?, ?, 'RegularPlay', 't')", (f"s{n}", team, minute, xg, outcome),
        )


def test_rebuild_reads_the_score_the_shots_and_the_deserved_result(db_conn):
    _seed_two_players_two_teams(db_conn)
    _match(db_conn)
    db_conn.commit()
    m = rebuild_match(db_conn, 100)
    assert m["home"]["score"] == 3 and m["home"]["xg"] == pytest.approx(0.38)
    assert m["away"]["xg"] == pytest.approx(0.4)
    assert [s["minute"] for s in m["shots"]] == [10, 30, 50, 70, 80]
    assert sum(1 for s in m["shots"] if s["goal"]) == 3
    assert m["deserved"]["home_win"] < 0.5
    assert m["own_goals_or_unshot"] == {"home": 0, "away": 0}


def test_unfinished_or_missing_matches_are_not_rebuilt(db_conn):
    _seed_two_players_two_teams(db_conn)
    _match(db_conn, status="LIVE")
    db_conn.commit()
    assert rebuild_match(db_conn, 100) is None
    assert rebuild_match(db_conn, 999) is None
