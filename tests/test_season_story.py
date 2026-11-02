from fpl_agent.models.season_story import season_story

from test_cohort import _seed


def test_story_weeks_and_moments(db_conn, monkeypatch):
    _seed(db_conn)
    monkeypatch.setattr("fpl_agent.models.rules.current_season", lambda conn: "2026-27")
    db_conn.execute("UPDATE events SET average_entry_score = 50 WHERE id = 1")
    db_conn.execute("INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, "
                    "average_entry_score, updated_at) VALUES (2, 'Gameweek 2', '2026-08-22T10:00:00Z', 1787392800, 1, 0, 0, 0, 40, 't0')")
    for ev, pts, rank, bench in ((1, 60, 500_000, 3), (2, 30, 900_000, 15)):
        db_conn.execute("INSERT INTO my_team_gw_summary (entry_id, event, points, total_points, overall_rank, event_transfers, "
                        "event_transfers_cost, points_on_bench, retrieved_at) VALUES (7, ?, ?, ?, ?, 0, 0, ?, 't0')", (ev, pts, pts, rank, bench))
        db_conn.execute("INSERT INTO my_team_picks (entry_id, event, player_id, squad_slot, multiplier, is_captain, is_vice_captain, "
                        "active_chip, retrieved_at) VALUES (7, ?, 1, 1, 2, 1, 0, NULL, 't0')", (ev,))
    db_conn.commit()

    s = season_story(db_conn, 7)
    assert [w["points"] for w in s["weeks"]] == [60, 30]
    assert s["moments"]["best_week"] == 1 and s["moments"]["worst_week"] == 2
    assert s["moments"]["worst_fall"] == (2, -400_000)
    assert s["moments"]["worst_bench"] == 2
    assert s["weeks"][0]["captain"]["points"] == 10
