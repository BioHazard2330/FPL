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


def test_template_uses_sample_eo_when_available_even_if_raw_ownership_disagrees(db_conn):
    _seed(db_conn)  # Popular=40%, Backup=5%, MostPopular=60% raw ownership, all GKP

    # player_sample_ownership_history.event has a real FK to events(id) - _seed() above
    # doesn't create one, so this test needs its own (foreign_keys=ON on every connection).
    db_conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (1,'GW1','t0',0,0,0,0,0,'t0')"
    )

    # Backup (raw 5%, lowest) is actually the most EFFECTIVELY owned - a smaller
    # slice of managers own it, but nearly all of them captain it (multiplier=2),
    # so its multiplier-weighted EO overtakes MostPopular's larger-but-rarely-
    # captained raw ownership. 100 sampled managers throughout:
    #   Backup:       35 own it, all 35 captain it  -> sum_multiplier=70, eo=70.0
    #   Popular:      40 own it, none captain it     -> sum_multiplier=40, eo=40.0
    #   MostPopular:  60 own it, none captain it     -> sum_multiplier=60, eo=60.0
    db_conn.execute(
        "INSERT INTO player_sample_ownership_history "
        "(player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
        "VALUES (2, 1, 100, 35, 35, 70, 140, 't0')"  # eo_percent = 70.0
    )
    db_conn.execute(
        "INSERT INTO player_sample_ownership_history "
        "(player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
        "VALUES (1, 1, 100, 40, 0, 40, 40, 't0')"  # eo_percent = 40.0, Popular
    )
    db_conn.execute(
        "INSERT INTO player_sample_ownership_history "
        "(player_id, event, sample_size, owned_count, captained_count, sum_multiplier, sum_multiplier_sq, retrieved_at) "
        "VALUES (3, 1, 100, 60, 0, 60, 60, 't0')"  # eo_percent = 60.0, MostPopular
    )
    db_conn.commit()

    from fpl_agent.models.template import get_template
    result = get_template(db_conn, top_n_per_position=3)

    # Backup's EO (70.0) now beats MostPopular's EO (60.0), flipping the raw-ownership order
    assert [p.web_name for p in result] == ["Backup", "MostPopular", "Popular"]
    assert result[0].eo_source == "sampled"
    assert result[0].effective_ownership_percent == 70.0
