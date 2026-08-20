from click.testing import CliRunner

from fpl_agent.cli.main import cli
from test_optimization_squad import _seed


def _seed_fixture(conn, event=1, finished=0, team_h=1, team_a=2):
    now = "t0"
    conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, updated_at) "
        "VALUES (?,?,?,1,0,0,0,1,?)", (event, f"Gameweek {event}", "2026-08-21T17:30:00Z", now),
    )
    conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (1,1,?,?,?,?,?,1,?)",
        (event, "2026-08-21T17:30:00Z", team_h, team_a, finished, now),
    )
    conn.commit()


class _FakeAdapter:
    """Returns each payload in `payloads` in order, one per call - mirrors
    the real FPLApiAdapter's `.fetch_event_live(event).data` shape without
    a network call."""

    def __init__(self, payloads):
        self._payloads = iter(payloads)

    def fetch_event_live(self, event):
        class _Resp:
            def __init__(self, data):
                self.data = data
        return _Resp(next(self._payloads))


class _RecordingNotifier:
    def __init__(self):
        self.sent = []

    def send(self, alert):
        self.sent.append(alert)


def test_live_watch_stops_immediately_when_all_fixtures_already_finished(db_conn, monkeypatch):
    """No live match to watch - the command must exit cleanly without ever
    attempting a network fetch."""
    import fpl_agent.cli.main as main_mod

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_fixture(db_conn, finished=1)

    class _FetchForbiddenAdapter:
        def fetch_event_live(self, event):
            raise AssertionError("must not fetch live data once every fixture is finished")

    monkeypatch.setattr(main_mod, "FPLApiAdapter", _FetchForbiddenAdapter)

    result = CliRunner().invoke(cli, ["live-watch", "--squad", "1,2,3"])

    assert result.exit_code == 0, result.output
    assert "all fixtures finished" in result.output


def test_live_watch_fires_a_goal_notification_on_the_second_poll(db_conn, monkeypatch):
    """First poll seeds the baseline (no false retroactive alert); the
    second poll sees a real goals_scored increase for a tracked squad
    player and must push exactly one 'goal' alert through the notifier."""
    import fpl_agent.cli.main as main_mod

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_fixture(db_conn, finished=0)

    payloads = [
        {"elements": [{"id": 1, "stats": {"minutes": 45, "bps": 20, "goals_scored": 0, "assists": 0}, "explain": [{"fixture": 1}]}]},
        {"elements": [{"id": 1, "stats": {"minutes": 60, "bps": 35, "goals_scored": 1, "assists": 0}, "explain": [{"fixture": 1}]}]},
    ]
    monkeypatch.setattr(main_mod, "FPLApiAdapter", lambda: _FakeAdapter(payloads))

    recorder = _RecordingNotifier()
    monkeypatch.setattr(main_mod, "configured_notifiers", lambda conn: recorder)

    sleep_calls = {"n": 0}

    def _fake_sleep(_seconds):
        sleep_calls["n"] += 1
        if sleep_calls["n"] >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(main_mod.time, "sleep", _fake_sleep)

    result = CliRunner().invoke(cli, ["live-watch", "--squad", "1", "--interval", "1"])

    assert result.exit_code == 0, result.output
    assert "stopped" in result.output
    assert len(recorder.sent) == 1
    assert recorder.sent[0].event_type == "goal"
    assert recorder.sent[0].entity_id == 1


def test_live_watch_no_deliver_uses_terminal_only(db_conn, monkeypatch):
    """--no-deliver must bypass configured_notifiers entirely (no Telegram/
    Discord network calls even if configured) and print to the terminal."""
    import fpl_agent.cli.main as main_mod

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_fixture(db_conn, finished=1)

    def _boom(conn):
        raise AssertionError("configured_notifiers must not be called with --no-deliver")
    monkeypatch.setattr(main_mod, "configured_notifiers", _boom)
    monkeypatch.setattr(main_mod, "FPLApiAdapter", lambda: _FakeAdapter([]))

    result = CliRunner().invoke(cli, ["live-watch", "--squad", "1", "--no-deliver"])

    assert result.exit_code == 0, result.output


def test_live_watch_prunes_raw_files_so_a_long_session_does_not_accumulate_them(db_conn, monkeypatch):
    """Real gap found 2026-08-20: fetch_event_live's save_raw() writes a
    fresh timestamped file every call (never overwrites) - at a 75s default
    interval over a multi-hour match, that's ~150 files per session, and
    the regular scheduler's own prune_raw() cycle isn't guaranteed to run
    inside a single watch session. live-watch must prune its own raw
    output rather than relying on a concurrent process to clean up after it."""
    import fpl_agent.cli.main as main_mod

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_fixture(db_conn, finished=0)

    payloads = [{"elements": [{"id": 1, "stats": {"minutes": 45, "bps": 20, "goals_scored": 0, "assists": 0}, "explain": [{"fixture": 1}]}]}]
    monkeypatch.setattr(main_mod, "FPLApiAdapter", lambda: _FakeAdapter(payloads))
    monkeypatch.setattr(main_mod, "configured_notifiers", lambda conn: _RecordingNotifier())

    prune_calls = []
    monkeypatch.setattr(main_mod, "prune_raw", lambda hours: prune_calls.append(hours))

    class _FakeBudget:
        raw_retention_hours = 48
    monkeypatch.setattr(main_mod, "load_storage_budget", lambda: _FakeBudget())

    def _fake_sleep(_seconds):
        raise KeyboardInterrupt
    monkeypatch.setattr(main_mod.time, "sleep", _fake_sleep)

    result = CliRunner().invoke(cli, ["live-watch", "--squad", "1", "--interval", "1"])

    assert result.exit_code == 0, result.output
    assert prune_calls == [48]


def test_live_watch_defaults_to_the_recommended_squad_when_none_given(db_conn, monkeypatch):
    import fpl_agent.cli.main as main_mod

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _seed_fixture(db_conn, finished=1)
    monkeypatch.setattr(main_mod, "FPLApiAdapter", lambda: _FakeAdapter([]))

    result = CliRunner().invoke(cli, ["live-watch"])

    assert result.exit_code == 0, result.output
    assert "tracking the current recommended squad" in result.output
