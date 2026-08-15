from fpl_agent.models.price_forecast import classify_price_change


def _seed_player(conn, player_id=1):
    conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Team A','TMA','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        f"INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        f"VALUES ({player_id},{player_id},'P{player_id}',1,1,'a','2026-01-01T00:00:00Z')"
    )
    conn.execute("INSERT INTO app_meta (key, value, updated_at) VALUES ('total_players','1000000','2026-01-01T00:00:00Z')")
    conn.commit()


def test_classify_rise_likely_when_net_in_exceeds_threshold(db_conn):
    _seed_player(db_conn)
    db_conn.execute(
        "INSERT INTO player_transfer_momentum_history "
        "(player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from, valid_until) "
        "VALUES (1, 8000, 500, 8000, 500, '2026-01-01T00:00:00Z', NULL)"
    )
    db_conn.commit()
    forecast = classify_price_change(db_conn, 1)
    assert forecast.direction == "RISE_LIKELY"
    assert forecast.momentum_ratio > 0
    assert forecast.confidence == "low"


def test_classify_fall_likely_when_net_out_exceeds_threshold(db_conn):
    _seed_player(db_conn)
    db_conn.execute(
        "INSERT INTO player_transfer_momentum_history "
        "(player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from, valid_until) "
        "VALUES (1, 500, 8000, 500, 8000, '2026-01-01T00:00:00Z', NULL)"
    )
    db_conn.commit()
    forecast = classify_price_change(db_conn, 1)
    assert forecast.direction == "FALL_LIKELY"
    assert forecast.momentum_ratio < 0


def test_classify_stable_when_momentum_below_threshold(db_conn):
    _seed_player(db_conn)
    db_conn.execute(
        "INSERT INTO player_transfer_momentum_history "
        "(player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from, valid_until) "
        "VALUES (1, 550, 500, 550, 500, '2026-01-01T00:00:00Z', NULL)"
    )
    db_conn.commit()
    forecast = classify_price_change(db_conn, 1)
    assert forecast.direction == "STABLE"


def test_classify_stable_when_no_momentum_row_yet(db_conn):
    _seed_player(db_conn)
    forecast = classify_price_change(db_conn, 1)
    assert forecast.direction == "STABLE"
    assert forecast.momentum_ratio == 0.0
