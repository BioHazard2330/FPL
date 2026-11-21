import json

from fpl_agent.ingestion import match_detail
from fpl_agent.models import roles


def test_role_for_reads_the_formation_grid():
    assert match_detail.role_for(0.1, 0.5, 4) == "GK"
    assert match_detail.role_for(0.292, 0.875, 4) == "FB"
    assert match_detail.role_for(0.292, 0.5, 4) == "CB"
    assert match_detail.role_for(0.485, 0.9, 3) == "WB"
    assert match_detail.role_for(0.485, 0.3, 4) == "DM"
    assert match_detail.role_for(0.678, 0.837, 4) == "W"
    assert match_detail.role_for(0.678, 0.5, 4) == "AM"
    assert match_detail.role_for(0.87, 0.5, 4) == "ST"


def test_parse_takes_layout_and_flattens_stats():
    details = {"content": {
        "lineup": {"homeTeam": {"formation": "4-3-3", "starters": [
            {"id": 1, "horizontalLayout": {"x": 0.1, "y": 0.5}},
            {"id": 2, "horizontalLayout": {"x": 0.29, "y": 0.1}},
            {"id": 3, "horizontalLayout": {"x": 0.29, "y": 0.4}}], "subs": [{"id": 4}]}, "awayTeam": {}},
        "playerStats": {"2": {"id": 2, "stats": [{"key": "attack", "stats": {"Corners": {"key": "corners", "stat": {"value": 3, "type": "integer"}},
                                                                          "Accurate crosses": {"key": "accurate_crosses", "stat": {"value": 2, "total": 5, "type": "fractionWithPercentage"}}}}]},
                        "4": {"id": 4, "stats": [{"key": "top", "stats": {"Minutes played": {"key": "minutes_played", "stat": {"value": 20, "type": "integer"}}}}]}},
    }}
    rows = {r["fotmob_player_id"]: r for r in match_detail.parse(details)}
    assert set(rows) == {2, 4}
    assert rows[2]["role"] == "FB" and rows[2]["stats"] == {"corners": 3, "accurate_crosses": 2, "accurate_crosses_total": 5}
    assert rows[4]["started"] == 0 and rows[4]["role"] is None


def _seed(conn):
    conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'A','AAA','t'), (2,2,'B','BBB','t')")
    conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (2,'D','DEF','Ds','t'), (3,'M','MID','Ms','t')")
    conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (10,10,'Wingback',1,2,'a',0,'t'), (11,11,'Taker',1,3,'a',0,'t')")
    for m in range(1, 5):
        conn.execute("INSERT INTO match_intelligence (id, fotmob_match_id, competition, kickoff_utc, home_team_id, away_team_id, status, home_score, away_score, source, retrieved_at) "
                     "VALUES (?,?,'Premier League',?,1,2,'FULL_TIME',1,0,'fotmob','t')", (m, f"fm{m}", f"2026-09-0{m}T15:00:00Z"))
        conn.execute("INSERT INTO player_match_detail VALUES (?,100,10,1,1,'W',0.68,0.1,'4-3-3',?,'t')", (m, json.dumps({"minutes_played": 90, "touches_opp_box": 4})))
        corners = 0 if m < 3 else 5
        conn.execute("INSERT INTO player_match_detail VALUES (?,101,11,1,1,'CM',0.5,0.5,'4-3-3',?,'t')", (m, json.dumps({"minutes_played": 90, "corners": corners})))
    conn.commit()


def test_a_defender_playing_on_the_wing_is_out_of_position(db_conn):
    _seed(db_conn)
    oop = roles.out_of_position(db_conn)
    assert [(o["name"], o["plays_as"]) for o in oop] == [("Wingback", "W-L")]


def test_set_pieces_and_depth_chart(db_conn):
    _seed(db_conn)
    sp = roles.set_pieces(db_conn, 1)
    assert sp["corners"][0]["name"] == "Taker" and sp["corners"][0]["count"] == 10
    depth = roles.depth_chart(db_conn, 1)
    assert {s["slot"] for s in depth["eleven"]} == {"W-L", "CM"} and depth["matches"] == 4
