import pytest


@pytest.fixture
def db_conn(tmp_path, monkeypatch):
    monkeypatch.setattr("fpl_agent.database.connection.DATA_DIR", tmp_path)
    monkeypatch.setattr("fpl_agent.database.connection.DB_PATH", tmp_path / "test.db")

    from fpl_agent.database.connection import get_connection
    from fpl_agent.database.migrate import run_migrations

    conn = get_connection()
    run_migrations(conn)
    yield conn
    conn.close()
