import pytest

from fpl_agent.models.fixture_outlook import team_fixture_outlook

from test_news_source_matching import _seed_two_players_two_teams


def _events(conn, upto=9):
    for n in range(1, upto + 1):
        conn.execute(
            "INSERT OR IGNORE INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, updated_at) "
            "VALUES (?, ?, 't', 0, 0, 0, 0, 0, 't')", (n, f"GW{n}"),
        )


def test_outlook_ranks_clubs_and_marks_blanks_and_doubles(db_conn):
    _seed_two_players_two_teams(db_conn)
    _events(db_conn)
    for fid, event, h, a in ((1, 7, 1, 2), (2, 8, 2, 1), (3, 8, 1, 2)):
        db_conn.execute(
            "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, 0, 't')", (fid, fid, event, f"2026-10-{10 + fid}T15:00:00Z", h, a),
        )
    db_conn.commit()

    out = team_fixture_outlook(db_conn, 7, window=3)
    assert set(out) == {1, 2}
    assert out[1]["fixtures"] == 3 and sorted(out[1]["events"]) == ["7", "8"]
    assert len(out[1]["events"]["8"]) == 2
    assert {out[1]["attack_rank"], out[2]["attack_rank"]} == {1, 2}
    assert out[1]["clubs_ranked"] == 2
    first = out[1]["events"]["7"][0]
    assert first["home"] is True and first["cs"] == pytest.approx(__import__("math").exp(-first["xg_against"]), abs=1e-3)


def test_a_finished_fixture_is_not_in_the_outlook(db_conn):
    _seed_two_players_two_teams(db_conn)
    _events(db_conn)
    db_conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1, 1, 7, '2026-10-11T15:00:00Z', 1, 2, 1, 1, 't')"
    )
    db_conn.commit()
    assert team_fixture_outlook(db_conn, 7) == {}
