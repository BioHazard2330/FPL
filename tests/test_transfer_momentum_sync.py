from fpl_agent.normalization.fpl_core import normalize_player_transfer_momentum
from fpl_agent.ingestion.sync import sync_transfer_momentum_history, sync_total_players


def _bootstrap_fixture():
    return {
        "total_players": 4066052,
        "elements": [
            {"id": 1, "transfers_in_event": 1000, "transfers_out_event": 200,
             "transfers_in": 5000, "transfers_out": 800},
            {"id": 2, "transfers_in_event": 50, "transfers_out_event": 3000,
             "transfers_in": 200, "transfers_out": 9000},
        ],
    }


def test_normalize_player_transfer_momentum_shape():
    rows = normalize_player_transfer_momentum(_bootstrap_fixture())
    assert rows == [
        {"player_id": 1, "transfers_in_event": 1000, "transfers_out_event": 200,
         "transfers_in": 5000, "transfers_out": 800},
        {"player_id": 2, "transfers_in_event": 50, "transfers_out_event": 3000,
         "transfers_in": 200, "transfers_out": 9000},
    ]


def _seed_player(conn, player_id):
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) "
        "VALUES (1,1,'Team A','TMA','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (1,'Forward','FWD','Forwards','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        f"INSERT INTO players (id, code, web_name, team_id, element_type, status, updated_at) "
        f"VALUES ({player_id},{player_id},'P{player_id}',1,1,'a','2026-01-01T00:00:00Z')"
    )
    conn.commit()


def test_sync_transfer_momentum_history_inserts_and_updates_only_on_change(db_conn):
    _seed_player(db_conn, 1)
    rows = [{"player_id": 1, "transfers_in_event": 1000, "transfers_out_event": 200,
             "transfers_in": 5000, "transfers_out": 800}]

    changed_1 = sync_transfer_momentum_history(db_conn, rows, "2026-08-15T10:00:00Z")
    db_conn.commit()
    assert changed_1 == 1

    changed_2 = sync_transfer_momentum_history(db_conn, rows, "2026-08-15T11:00:00Z")
    db_conn.commit()
    assert changed_2 == 0  # identical values, no new row

    rows[0]["transfers_in_event"] = 2000
    changed_3 = sync_transfer_momentum_history(db_conn, rows, "2026-08-15T12:00:00Z")
    db_conn.commit()
    assert changed_3 == 1

    open_rows = db_conn.execute(
        "SELECT transfers_in_event FROM player_transfer_momentum_history "
        "WHERE player_id=1 AND valid_until IS NULL"
    ).fetchall()
    assert len(open_rows) == 1
    assert open_rows[0]["transfers_in_event"] == 2000

    closed_rows = db_conn.execute(
        "SELECT transfers_in_event FROM player_transfer_momentum_history "
        "WHERE player_id=1 AND valid_until IS NOT NULL"
    ).fetchall()
    assert len(closed_rows) == 1
    assert closed_rows[0]["transfers_in_event"] == 1000


def test_sync_total_players_upserts_app_meta(db_conn):
    sync_total_players(db_conn, _bootstrap_fixture(), "2026-08-15T10:00:00Z")
    db_conn.commit()
    row = db_conn.execute("SELECT value FROM app_meta WHERE key='total_players'").fetchone()
    assert row["value"] == "4066052"

    sync_total_players(db_conn, {"total_players": 4100000}, "2026-08-15T11:00:00Z")
    db_conn.commit()
    row = db_conn.execute("SELECT value FROM app_meta WHERE key='total_players'").fetchone()
    assert row["value"] == "4100000"
