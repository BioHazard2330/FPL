"""Real regression coverage for THE MATCHWEEK payload (2026-09-09) - the
league table, the fixture calendar and the full-time detail. The table is
computed here rather than read from a standings feed, so the ordering and
points arithmetic are the things worth pinning down."""
import json

import pytest

from fpl_agent.monitoring.api.matchweek_payload import _leaderboards, _league_table, _matchweeks, _team_rows
from test_optimization_squad import _PLAYERS, _seed


def _event(conn, event, deadline, finished=0):
    conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, updated_at) VALUES (?,?,?,?,?,0,0,0,?)",
        (event, f"Gameweek {event}", deadline, 1789038000 + event * 604800, finished, "t0"),
    )


def _fixture(conn, fid, event, h, a, hs=None, a_s=None, finished=0, ko="2026-09-12T14:00:00Z"):
    conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, team_h_score, "
        "team_a_score, finished, started, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (fid, 7000 + fid, event, ko, h, a, hs, a_s, finished, finished, "t0"),
    )


def test_league_table_applies_real_points_and_the_real_tiebreak_order(db_conn):
    """Three for a win, one for a draw, ordered points -> goal difference ->
    goals for. Team 1 and team 2 finish level on points, and goal difference
    must separate them."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _event(db_conn, 1, "2026-09-04T17:30:00Z", finished=1)
    # team 1 beats team 3 by three; team 2 beats team 4 by one
    _fixture(db_conn, 1, 1, 1, 3, hs=3, a_s=0, finished=1)
    _fixture(db_conn, 2, 1, 2, 4, hs=1, a_s=0, finished=1)
    db_conn.commit()

    teams = _team_rows(db_conn)
    table = _league_table(db_conn, teams, set())
    json.dumps(table)
    by_id = {r["team_id"]: r for r in table}

    assert by_id[1]["points"] == 3 and by_id[1]["won"] == 1 and by_id[1]["gd"] == 3
    assert by_id[2]["points"] == 3 and by_id[2]["gd"] == 1
    assert by_id[3]["points"] == 0 and by_id[3]["lost"] == 1
    # level on points, separated by goal difference
    assert by_id[1]["position"] < by_id[2]["position"]
    # positions are a dense 1..N ranking over every real club
    assert [r["position"] for r in table] == list(range(1, len(table) + 1))


def test_league_table_counts_a_draw_as_one_point_each_and_records_form(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _event(db_conn, 1, "2026-09-04T17:30:00Z", finished=1)
    _fixture(db_conn, 1, 1, 1, 2, hs=2, a_s=2, finished=1)
    db_conn.commit()

    by_id = {r["team_id"]: r for r in _league_table(db_conn, _team_rows(db_conn), set())}
    assert by_id[1]["points"] == 1 and by_id[1]["drawn"] == 1
    assert by_id[2]["points"] == 1
    assert by_id[1]["form"] == ["D"]


def test_league_table_shows_a_real_zero_row_before_a_ball_is_kicked(db_conn):
    """Never an absent club, never a fabricated projection - a season that has
    not started is a table of real zeroes."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    table = _league_table(db_conn, _team_rows(db_conn), set())
    assert len(table) == len(_team_rows(db_conn))
    assert all(r["played"] == 0 and r["points"] == 0 and r["form"] == [] for r in table)


def test_league_table_marks_the_users_own_clubs(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    table = _league_table(db_conn, _team_rows(db_conn), {1})
    assert {r["team_id"] for r in table if r["in_squad"]} == {1}


def test_matchweeks_carry_real_kickoffs_and_never_a_score_for_an_unplayed_game(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    _event(db_conn, 1, "2026-09-04T17:30:00Z", finished=1)
    _event(db_conn, 2, "2026-09-12T12:30:00Z")
    _fixture(db_conn, 1, 1, 1, 2, hs=2, a_s=1, finished=1, ko="2026-09-05T14:00:00Z")
    _fixture(db_conn, 2, 2, 3, 4, ko="2026-09-12T14:00:00Z")
    db_conn.commit()

    blocks = _matchweeks(db_conn, _team_rows(db_conn), {1})
    json.dumps(blocks)
    by_event = {b["event"]: b for b in blocks}

    played = by_event[1]["fixtures"][0]
    assert played["finished"] is True
    assert played["home"]["score"] == 2 and played["away"]["score"] == 1
    assert by_event[1]["complete"] is True
    assert played["has_squad_interest"] is True

    upcoming = by_event[2]["fixtures"][0]
    assert upcoming["finished"] is False
    assert upcoming["home"]["score"] is None and upcoming["away"]["score"] is None
    assert upcoming["kickoff_time"] == "2026-09-12T14:00:00Z"
    assert by_event[2]["complete"] is False
    assert upcoming["has_squad_interest"] is False


def test_leaderboards_exclude_a_player_with_no_stat_record(db_conn):
    """"We have no record" and "they did nothing" are different statements.
    A player without a snapshot row must not appear ranked as a zero."""
    _seed(db_conn, budget_tenths=950, club_limit=4)
    scorer, quiet = _PLAYERS[0][0], _PLAYERS[1][0]
    db_conn.execute(
        "INSERT INTO player_stats_snapshot (player_id, retrieved_at, stats_hash, total_points, minutes, "
        "goals_scored, assists, expected_goals, expected_assists) VALUES (?,?,?,?,?,?,?,?,?)",
        (scorer, "2026-09-05T00:00:00Z", "h1", 24, 270, 3, 1, 2.4, 0.6),
    )
    db_conn.commit()

    lb = _leaderboards(db_conn, _team_rows(db_conn), {scorer})
    json.dumps(lb)
    assert [r["player_id"] for r in lb["scorers"]] == [scorer]
    assert lb["scorers"][0]["goals"] == 3
    assert lb["scorers"][0]["is_mine"] is True
    # xGI is the real sum of the two expected components
    assert lb["underlying"][0]["xgi"] == pytest.approx(3.0)
    # the player with no snapshot row appears on no board at all
    assert all(quiet not in [r["player_id"] for r in board] for board in lb.values())


def test_leaderboards_are_empty_rather_than_zero_filled_on_a_bare_db(db_conn):
    _seed(db_conn, budget_tenths=950, club_limit=4)
    lb = _leaderboards(db_conn, _team_rows(db_conn), set())
    assert lb == {"scorers": [], "assists": [], "underlying": []}
