import copy
from datetime import datetime, timedelta, timezone

import pytest
from click.testing import CliRunner

import fpl_agent.cli.main as main_mod
import fpl_agent.ingestion.fotmob_source as fotmob_mod
import fpl_agent.scheduler.process_lock as process_lock_mod
from fpl_agent.cli.main import cli
from fpl_agent.ingestion.fotmob_source import FotMobFetchError
from test_fotmob_source import _DETAILS_PAYLOAD, _seed, _seed_match_intelligence_row


@pytest.fixture(autouse=True)
def _isolated_live_poll_lock(tmp_path, monkeypatch):
    """Real safety fix, not incidental: this file's tests invoke the actual
    `live-match-poll` CLI command, which now acquires a real singleton
    lock (`scheduler/process_lock.py`, 2026-08-29). Without this, tests
    would read/write the REAL production `data/live_poll.lock` file - on
    this project's own real dev machine that file can be actively held by
    a genuinely running `FPLAgentLivePoll` scheduled task, so an
    unisolated test run could either spuriously fail (a real live lock
    blocking a `--interval` test that expects success) or, worse, race a
    real production process. Every test in this file gets its own
    per-test tmp_path lock file instead.

    Same real isolation gap found + fixed for `DATA_DIR` (2026-08-28 frontend
    QA pass): `live-match-poll` also writes `live_snapshot.json` (and, on a
    FULL_TIME tick, the full `dashboard.html`) via `cli/main.py`'s own
    per-call-computed `DATA_DIR` - unpatched, this file's tests were silently
    overwriting the REAL production `data/live_snapshot.json` with this
    file's synthetic fixture squad on every run (confirmed live: found
    fabricated "P1"/"P20" player rows in the real file after a local test
    run) - a genuine violation of this project's own no-fabrication rule
    applied to a file the live dashboard trusts as real."""
    monkeypatch.setattr(process_lock_mod, "DEFAULT_LOCK_PATH", tmp_path / "live_poll.lock")
    monkeypatch.setattr(main_mod, "DATA_DIR", tmp_path)


def _live_payload(minute=17, home_score=0, away_score=0):
    payload = copy.deepcopy(_DETAILS_PAYLOAD)
    payload["general"]["started"] = True
    payload["header"]["status"] = {
        "started": True, "finished": False, "liveTime": {"short": f"{minute}'"},
    }
    payload["header"]["teams"][0]["score"] = home_score
    payload["header"]["teams"][1]["score"] = away_score
    payload["content"]["matchFacts"] = {"events": {"events": [
        {"eventId": 1, "type": "Goal", "time": 15, "isHome": True,
         "player": {"id": 1, "name": "Test Player"}, "fullName": "Test Player"},
    ]}}
    payload["content"]["shotmap"] = {"shots": [
        {"id": 501, "eventType": "Miss", "teamId": 9825, "playerId": 2,
         "playerName": "Unknown FotMob Player", "fullName": "Unknown FotMob Player", "min": 5},
    ], "Periods": {"All": []}}
    return payload


def _full_time_payload():
    payload = _live_payload()
    payload["general"]["finished"] = True
    payload["header"]["status"] = {"started": True, "finished": True}
    return payload


def _stub(monkeypatch, payload):
    monkeypatch.setattr(fotmob_mod, "find_match", lambda day, h, a: "5795363")
    monkeypatch.setattr(fotmob_mod, "fetch_match_details", lambda mid: payload)
    monkeypatch.setattr(fotmob_mod, "save_raw", lambda name, data: "raw/path.json")


def _run_with_sleep_limit(monkeypatch, args, max_calls=1):
    import fpl_agent.cli.main as main_mod

    calls = {"n": 0, "intervals": []}

    def _fake_sleep(seconds):
        calls["intervals"].append(seconds)
        calls["n"] += 1
        if calls["n"] >= max_calls:
            raise KeyboardInterrupt

    monkeypatch.setattr(main_mod.time, "sleep", _fake_sleep)
    result = CliRunner().invoke(cli, args)
    return result, calls


def test_pre_match_uses_the_slow_pre_kickoff_interval(db_conn, monkeypatch):
    kickoff = datetime.now(timezone.utc) + timedelta(minutes=30)
    _seed_match_intelligence_row(db_conn, "PRE_MATCH", kickoff)
    _stub(monkeypatch, _DETAILS_PAYLOAD)

    result, calls = _run_with_sleep_limit(monkeypatch, ["live-match-poll", "--interval", "20"])

    assert result.exit_code == 0, result.output
    assert calls["intervals"] == [80]  # max(20*4, 60)


def test_live_match_uses_the_fast_interval(db_conn, monkeypatch):
    kickoff = datetime.now(timezone.utc) - timedelta(minutes=17)
    _seed_match_intelligence_row(db_conn, "LIVE", kickoff)
    _stub(monkeypatch, _live_payload())

    result, calls = _run_with_sleep_limit(monkeypatch, ["live-match-poll", "--interval", "20"])

    assert result.exit_code == 0, result.output
    assert calls["intervals"] == [20]


def test_a_match_going_live_for_the_first_time_triggers_an_immediate_dashboard_regen(db_conn, monkeypatch):
    """Real bug found + fixed 2026-08-29 (direct user report: "games online
    but i dont see it on dashboard"). `_write_dashboard()` used to only ever
    fire on a real FULL_TIME transition (a deliberate 2026-08-28 perf fix) -
    a match's own FIRST transition into LIVE never got one, so a brand-new
    match had no DOM card for the browser's ~10s snapshot poll to patch
    (that poll can only update an ALREADY-rendered card). Seeds a real
    PRE_MATCH prior status with a payload reporting LIVE - a genuine
    not-live -> live transition - and asserts the real regen fires."""
    kickoff = datetime.now(timezone.utc) - timedelta(minutes=2)
    _seed_match_intelligence_row(db_conn, "PRE_MATCH", kickoff)
    _stub(monkeypatch, _live_payload())

    result, calls = _run_with_sleep_limit(monkeypatch, ["live-match-poll", "--interval", "20"])

    assert result.exit_code == 0, result.output
    assert "triggering an immediate dashboard regen" in result.output


def test_a_match_still_live_on_a_later_tick_does_not_re_trigger_the_regen(db_conn, monkeypatch):
    """The real trigger must fire only on the genuine transition, never on
    every tick a match simply stays live (that would undo the 2026-08-28
    perf fix this same trigger is layered onto)."""
    kickoff = datetime.now(timezone.utc) - timedelta(minutes=17)
    _seed_match_intelligence_row(db_conn, "LIVE", kickoff)
    _stub(monkeypatch, _live_payload())

    result, calls = _run_with_sleep_limit(monkeypatch, ["live-match-poll", "--interval", "20"])

    assert result.exit_code == 0, result.output
    assert "triggering an immediate dashboard regen" not in result.output


def test_full_time_stops_the_poller(db_conn, monkeypatch):
    kickoff = datetime.now(timezone.utc) - timedelta(minutes=90)
    _seed_match_intelligence_row(db_conn, "LIVE", kickoff)
    _stub(monkeypatch, _full_time_payload())

    result = CliRunner().invoke(cli, ["live-match-poll", "--interval", "20"])

    assert result.exit_code == 0, result.output
    assert "FULL_TIME" in result.output
    assert "no tracked match left to poll" in result.output


def test_second_instance_exits_cleanly_when_a_real_live_lock_is_held(db_conn, monkeypatch):
    """Direct P0 acceptance test: "two instances must never run
    simultaneously... second instance exits cleanly." A DIFFERENT pid than
    this test's own (the lock code correctly treats a lock file matching
    its own pid as self-owned/reclaimable, not "someone else holds it" -
    so a genuine other-holder simulation needs a different pid + a
    monkeypatched liveness check, same real seam
    `test_process_lock.py::test_acquire_fails_when_a_real_live_process_
    holds_the_lock` already uses)."""
    import os

    other_pid = os.getpid() + 1
    process_lock_mod.DEFAULT_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    process_lock_mod.DEFAULT_LOCK_PATH.write_text(f"{other_pid}\nreal\n", encoding="utf-8")
    monkeypatch.setattr(process_lock_mod, "_pid_is_alive", lambda pid: True)

    result = CliRunner().invoke(cli, ["live-match-poll", "--interval", "20"])

    assert result.exit_code == 0, result.output
    assert "already running" in result.output
    # Must never overwrite the still-live holder's real lock.
    assert process_lock_mod.DEFAULT_LOCK_PATH.read_text().splitlines()[0] == str(other_pid)


def test_stale_lock_from_a_crashed_prior_run_is_reclaimed_by_the_real_cli(db_conn, monkeypatch):
    """Direct P0 acceptance test: "test stale-lock recovery after process
    crash/restart", exercised through the actual CLI command, not just the
    lock module in isolation."""
    kickoff = datetime.now(timezone.utc) + timedelta(minutes=30)
    _seed_match_intelligence_row(db_conn, "PRE_MATCH", kickoff)
    _stub(monkeypatch, _DETAILS_PAYLOAD)
    process_lock_mod.DEFAULT_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    process_lock_mod.DEFAULT_LOCK_PATH.write_text("999999999\nstale\n", encoding="utf-8")  # a real, guaranteed-dead pid

    result, calls = _run_with_sleep_limit(monkeypatch, ["live-match-poll", "--interval", "20"])

    assert result.exit_code == 0, result.output
    assert "already running" not in result.output
    assert calls["intervals"] == [80]  # the real poll loop actually ran


def test_fotmob_failure_shows_delayed_state_and_backs_off(db_conn, monkeypatch):
    kickoff = datetime.now(timezone.utc) - timedelta(minutes=17)
    _seed_match_intelligence_row(db_conn, "LIVE", kickoff)

    def boom(mid):
        raise FotMobFetchError("simulated 503")

    monkeypatch.setattr(fotmob_mod, "find_match", lambda day, h, a: "5795363")
    monkeypatch.setattr(fotmob_mod, "fetch_match_details", boom)

    result, calls = _run_with_sleep_limit(monkeypatch, ["live-match-poll", "--interval", "20"])

    assert result.exit_code == 0, result.output
    assert "Live data delayed" in result.output
    assert calls["intervals"] == [40]  # first backoff: interval * 2**1


def test_duplicate_poll_does_not_create_duplicate_feed_items(db_conn, monkeypatch):
    _seed_match_intelligence_row(db_conn, "PRE_MATCH", datetime.now(timezone.utc))
    _stub(monkeypatch, _live_payload())

    fotmob_mod.sync_match(db_conn, "Arsenal", "Coventry City", datetime.now(timezone.utc).date())
    fotmob_mod.sync_match(db_conn, "Arsenal", "Coventry City", datetime.now(timezone.utc).date())

    count = db_conn.execute("SELECT COUNT(*) FROM match_events").fetchone()[0]
    assert count == 2  # one Goal (matchFacts) + one Shot (shotmap) - not 4


def test_new_incident_is_persisted_with_real_provenance(db_conn, monkeypatch):
    _seed_match_intelligence_row(db_conn, "PRE_MATCH", datetime.now(timezone.utc))
    _stub(monkeypatch, _live_payload())

    fotmob_mod.sync_match(db_conn, "Arsenal", "Coventry City", datetime.now(timezone.utc).date())

    rows = db_conn.execute(
        "SELECT event_type, minute, source, retrieved_at, player_id FROM match_events ORDER BY minute"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["event_type"] == "Shot"
    assert rows[0]["minute"] == 5
    assert rows[0]["source"] == "fotmob"
    assert rows[0]["retrieved_at"] is not None
    assert rows[1]["event_type"] == "Goal"
    assert rows[1]["player_id"] == 1  # resolved via player_match_state's fotmob_player_id crosswalk
