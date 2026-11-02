from fpl_agent.models.chip_calendar import chip_calendar

from test_news_source_matching import _seed_two_players_two_teams


def test_blanks_and_doubles_come_from_the_fixture_list(db_conn):
    _seed_two_players_two_teams(db_conn)
    for ev in (1, 2, 3):
        db_conn.execute("INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, updated_at) "
                        "VALUES (?, ?, '2026-08-15T10:00:00Z', 1786788000, 0, 0, 0, 0, 't0')", (ev, f"Gameweek {ev}"))
    rows = [(1, 1, 1, 2), (2, 1, 2, 1), (3, 1, 1, 2), (4, 3, 1, 2), (5, None, 2, 1)]
    for fid, ev, h, a in rows:
        db_conn.execute("INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
                        "VALUES (?, ?, ?, '2026-08-16T14:00:00Z', ?, ?, 0, 0, 't0')", (fid, fid, ev, h, a))
    db_conn.commit()
    d = chip_calendar(db_conn, None, {1})
    w1, w2, w3 = d["weeks"][0], d["weeks"][1], d["weeks"][2]
    assert len(w1["double"]) == 2 and w1["squad_double"] == 1
    assert w2["fixtures"] == 0 and w2["blank"] == []
    assert w3["fixtures"] == 1 and w3["double"] == []
    assert d["unscheduled"] and d["announced"] is True
