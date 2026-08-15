def test_transfer_momentum_table_exists(db_conn):
    tables = {
        r["name"]
        for r in db_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "player_transfer_momentum_history" in tables


def test_transfer_momentum_valid_from_until_pattern(db_conn):
    db_conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'Team A','TMA','2026-01-01T00:00:00Z')"
    )
    db_conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','2026-01-01T00:00:00Z')"
    )
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        "VALUES (1,1,'Player A',1,1,'a','2026-01-01T00:00:00Z')"
    )
    db_conn.execute(
        "INSERT INTO player_transfer_momentum_history "
        "(player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from, valid_until) "
        "VALUES (1, 1000, 200, 5000, 800, '2026-01-01T00:00:00Z', NULL)"
    )
    db_conn.commit()
    row = db_conn.execute(
        "SELECT transfers_in_event, valid_until FROM player_transfer_momentum_history WHERE player_id=1"
    ).fetchone()
    assert row["transfers_in_event"] == 1000
    assert row["valid_until"] is None
