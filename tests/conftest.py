import pytest


@pytest.fixture(autouse=True, scope="session")
def _keep_tests_out_of_the_real_log():
    """CLI commands invoked by tests call `setup_logging`, which would attach the real `logs/fpl_agent.log`; simulated
    failures then read as production errors. Marked configured up front so it never attaches."""
    from fpl_agent import logging_setup

    logging_setup._configured = True
    yield


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
