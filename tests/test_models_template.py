from fpl_agent.models.template import get_template


def _seed(conn):
    now = "t0"
    conn.execute(
        "INSERT INTO teams (id,code,name,short_name,strength_overall_home,strength_overall_away,"
        "strength_attack_home,strength_attack_away,strength_defence_home,strength_defence_away,pulse_id,updated_at) "
        "VALUES (1,1,'T1','T1',3,3,0,0,0,0,1,?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO element_types (id,singular_name,singular_name_short,plural_name,squad_min_play,"
        "squad_max_play,squad_select,updated_at) VALUES (1,'Goalkeeper','GKP','Goalkeepers',1,1,2,?)",
        (now,),
    )
    for pid, name, ownership in ((1, "Popular", 40.0), (2, "Backup", 5.0), (3, "MostPopular", 60.0)):
        conn.execute(
            "INSERT INTO players (id,code,web_name,team_id,element_type,status,removed,updated_at) "
            "VALUES (?,?,?,1,1,'a',0,?)",
            (pid, pid, name, now),
        )
        conn.execute(
            "INSERT INTO player_ownership_history (player_id, selected_by_percent, valid_from, valid_until) "
            "VALUES (?,?,?,NULL)",
            (pid, ownership, now),
        )
    conn.commit()


def test_template_orders_by_ownership_desc(db_conn):
    _seed(db_conn)

    result = get_template(db_conn, top_n_per_position=2)

    assert [p.web_name for p in result] == ["MostPopular", "Popular"]


def test_template_respects_top_n_limit(db_conn):
    _seed(db_conn)

    result = get_template(db_conn, top_n_per_position=1)

    assert len(result) == 1
    assert result[0].web_name == "MostPopular"
