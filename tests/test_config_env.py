import os

from fpl_agent import config as config_mod


def test_load_dotenv_sets_missing_var(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ODDS_API_KEY=test-key-123\n# a comment\n\nSOME_OTHER=value\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("ODDS_API_KEY", raising=False)

    config_mod.load_dotenv()

    assert os.environ["ODDS_API_KEY"] == "test-key-123"
    # load_dotenv() writes directly to os.environ, bypassing monkeypatch's
    # tracked undo stack. monkeypatch.delenv() here would capture this leaked
    # value as the "restore" target and put it back into the real process
    # environment at teardown. Pop directly instead.
    os.environ.pop("ODDS_API_KEY", None)
    os.environ.pop("SOME_OTHER", None)


def test_load_dotenv_never_overwrites_real_env_var(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ODDS_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("ODDS_API_KEY", "from-real-env")

    config_mod.load_dotenv()

    assert os.environ["ODDS_API_KEY"] == "from-real-env"
    monkeypatch.delenv("ODDS_API_KEY", raising=False)


def test_load_dotenv_missing_file_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)
    config_mod.load_dotenv()  # no .env file in tmp_path - must not raise


def test_get_odds_api_key_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    assert config_mod.get_odds_api_key() is None


def test_get_odds_api_key_returns_value_when_set(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "abc123")
    assert config_mod.get_odds_api_key() == "abc123"
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
