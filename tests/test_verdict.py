from fpl_agent.models import track_record, verdict


def _seed(conn):
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'A','AAA','t'), (2,2,'B','BBB','t')")
    conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (3,'M','MID','Ms','t')")
    for pid in range(1, 8):
        conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (?,?,?,1,3,'a',0,'t')", (pid, pid, f"P{pid}"))
        conn.execute("INSERT INTO player_price_history (player_id, value_tenths, valid_from, valid_until) VALUES (?, ?, 't', NULL)", (pid, 50 + pid))
        for e in range(1, 7):
            conn.execute("INSERT INTO player_gw_stats (player_id, event, season, minutes, goals, assists, clean_sheets, goals_conceded, own_goals, penalties_missed, penalties_saved, yellow_cards, red_cards, saves, bonus, total_points, retrieved_at) VALUES (?,?,?,90,0,0,0,0,0,0,0,0,0,0,0,?,'t')",
                         (pid, e, "2026-27", pid))
        for e in range(7, 10):
            conn.execute("INSERT INTO prediction_outcomes (player_id, event, season, predicted_median, actual_points, predicted_at) VALUES (?,?,?,?,?,'t')",
                         (pid, e, "2026-27", 4.0, 4.0 + (pid - 4)))
    conn.commit()


def test_track_record_carries_a_tenth_of_the_mean_miss(db_conn, monkeypatch):
    _seed(db_conn)
    monkeypatch.setattr("fpl_agent.models.rules.current_season", lambda conn: "2026-27")
    track_record.clear_cache()
    recs = track_record.records(db_conn)
    assert recs[7]["mean_miss"] == 3.0 and recs[7]["adjustment"] == 0.3
    assert recs[1]["adjustment"] == -0.3 and 4 not in {k for k, v in recs.items() if v["mean_miss"] != 0}


def test_verdict_ranks_returns_and_value_and_labels(db_conn, monkeypatch):
    _seed(db_conn)
    monkeypatch.setattr("fpl_agent.models.rules.current_season", lambda conn: "2026-27")
    track_record.clear_cache()
    v = verdict.build(db_conn, None, with_checks=False)
    assert v[7]["lenses"]["returns"] == 100 and v[1]["lenses"]["returns"] == 0
    assert v[7]["score"] > v[1]["score"]
    assert v[7]["label"] in ("Strong", "Good") and v[1]["label"] in ("Weak", "Avoid")
    assert v[7]["facts"]["last6"] == [7] * 6
