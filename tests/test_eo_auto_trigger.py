from datetime import datetime, timedelta, timezone

from fpl_agent.cli import main as cli_main

from test_news_source_matching import _seed_two_players_two_teams


def _event(conn, n, hours_from_now):
    stamp = (datetime.now(timezone.utc) + timedelta(hours=hours_from_now)).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, is_next, updated_at) "
        "VALUES (?, 'GW', ?, 0, 0, 0, 0, 0, 't')", (n, stamp),
    )


def _spy(monkeypatch, tmp_path):
    started = []
    exe = tmp_path / "fpl.exe"
    exe.write_text("")
    monkeypatch.setattr(cli_main.sys, "executable", str(tmp_path / "python.exe"))
    monkeypatch.setattr(cli_main, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(cli_main.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    return started


def test_a_locked_gameweek_without_a_sample_starts_one_background_run(db_conn, monkeypatch, tmp_path):
    _seed_two_players_two_teams(db_conn)
    _event(db_conn, 6, -48)
    _event(db_conn, 7, 12)
    db_conn.commit()
    started = _spy(monkeypatch, tmp_path)
    assert "GW6" in cli_main._maybe_trigger_eo_sample(db_conn)
    assert started and started[0][-2:] == ["--event", "6"]
    assert cli_main._maybe_trigger_eo_sample(db_conn) is None
    assert len(started) == 1


def test_no_run_when_the_locked_gameweek_is_already_sampled(db_conn, monkeypatch, tmp_path):
    from fpl_agent.models.effective_ownership import sample_season

    _seed_two_players_two_teams(db_conn)
    _event(db_conn, 6, -48)
    cols = [r["name"] for r in db_conn.execute("PRAGMA table_info(player_sample_ownership_history)")]
    values = {"player_id": 1, "event": 6, "sample_size": 10, "owned_count": 1, "captained_count": 0, "sum_multiplier": 1,
              "sum_multiplier_sq": 1, "retrieved_at": "t", "season": sample_season(db_conn)}
    use = {k: v for k, v in values.items() if k in cols}
    db_conn.execute(f"INSERT INTO player_sample_ownership_history ({','.join(use)}) VALUES ({','.join('?' * len(use))})", tuple(use.values()))
    db_conn.commit()
    started = _spy(monkeypatch, tmp_path)
    assert cli_main._maybe_trigger_eo_sample(db_conn) is None
    assert started == []


def test_nothing_before_any_deadline_has_passed(db_conn, monkeypatch, tmp_path):
    _seed_two_players_two_teams(db_conn)
    _event(db_conn, 1, 30)
    db_conn.commit()
    started = _spy(monkeypatch, tmp_path)
    assert cli_main._maybe_trigger_eo_sample(db_conn) is None
    assert started == []
