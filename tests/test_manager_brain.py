import json

from fpl_agent.models.manager_brain import manager_brain


def _seed(conn):
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'A','AAA','t'), (2,2,'B','BBB','t')")
    conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (3,'M','MID','Ms','t')")
    for pid, name in ((1, 'Star'), (2, 'Sub'), (3, 'Cover')):
        conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (?,?,?,1,3,'a',0,'t')", (pid, pid, name))
    for m in range(1, 6):
        conn.execute("INSERT INTO match_intelligence (id, fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, home_score, away_score, source, retrieved_at) "
                     "VALUES (?,?,'Premier League',?,1,2,'FULL_TIME',1,0,'fotmob','t')", (m, f"fm{m}", f"2026-09-0{m}T15:00:00Z"))
        subs = [{"minute": 60 + m, "team_id": 1, "off_id": 1, "on_id": 2, "margin": 1, "kind": "MANAGED_MINUTES"}]
        conn.execute("INSERT INTO match_story (match_id, engine_version, story_json, generated_at) VALUES (?,?,?,?)", (m, "v", json.dumps({"subs": subs}), "t"))
        starter = 1 if m < 5 else 3
        conn.execute("INSERT INTO player_match_state (match_id, player_id, team_id, started, minutes, source, retrieved_at, confidence) VALUES (?,?,1,1,90,'f','t','m')", (m, starter))
        conn.execute("INSERT INTO player_match_detail VALUES (?,?,?,1,1,'AM',0.7,0.5,'4-2-3-1',?,'t')", (m, 100 + starter, starter, json.dumps({"minutes_played": 90})))
    conn.commit()


def test_first_change_pairs_and_cover(db_conn):
    _seed(db_conn)
    b = manager_brain(db_conn, 1)
    assert b["first_change"]["ahead"] == {"median": 63, "matches": 5}
    assert b["first_off"][0]["name"] == "Star" and b["first_off"][0]["times"] == 5
    assert b["pairs"] == [{"off": "Star", "on": "Sub", "times": 5}]
    assert b["cover"][0]["name"] == "Star" and b["cover"][0]["stand_ins"][0]["name"] == "Cover"
