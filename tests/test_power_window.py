"""Power gating: the active window, the gate file the VBS launcher reads, the
`run-scheduled --gated` decision, and the dashboard server's idle behaviour."""
import time
from datetime import date, datetime, timedelta

import pytest

from fpl_agent.config import PowerConfig
from fpl_agent.live.sse_server import ActivityTracker, Broadcaster, LiveServer
from fpl_agent.models.fixtures import current_live_event
from fpl_agent.scheduler import power_window as pw

from test_news_source_matching import _seed_two_players_two_teams

HOUR = 3600
CFG = PowerConfig(window_lead_hours=24, post_deadline_grace_hours=3)


def _event(conn, event_id, deadline_epoch):
    conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, is_current, "
        "is_next, updated_at) VALUES (?,?,?,?,0,0,0,0,'t0')",
        (event_id, f"Gameweek {event_id}", datetime.utcfromtimestamp(deadline_epoch).isoformat() + "Z", deadline_epoch),
    )
    conn.commit()


# ------------------------------------------------------------------ the window


def test_window_opens_24h_before_the_next_deadline(db_conn):
    now = 1_800_000_000
    _event(db_conn, 7, now + 30 * HOUR)

    outside = pw.compute_window(db_conn, now, CFG)
    assert not outside.active and outside.start_epoch == now + 6 * HOUR

    inside = pw.compute_window(db_conn, now + 7 * HOUR, CFG)
    assert inside.active and inside.next_deadline_epoch == now + 30 * HOUR


def test_window_stays_open_through_the_post_deadline_grace_then_moves_on(db_conn):
    now = 1_800_000_000
    _event(db_conn, 7, now + HOUR)
    _event(db_conn, 8, now + 8 * 24 * HOUR)

    assert pw.compute_window(db_conn, now + 3 * HOUR, CFG).active  # 2h past, grace is 3h
    after = pw.compute_window(db_conn, now + 5 * HOUR, CFG)  # grace over: the next gameweek's window
    assert not after.active and after.next_deadline_epoch == now + 8 * 24 * HOUR


def test_no_deadline_on_record_is_outside_the_window(db_conn):
    assert not pw.compute_window(db_conn, 1_800_000_000, CFG).active


def test_disabling_power_gating_keeps_the_window_open_always(db_conn):
    cfg = PowerConfig(enabled=False)
    assert pw.compute_window(db_conn, 1_800_000_000, cfg).active


# ------------------------------------------------------------------- gate file


def test_gate_file_round_trips_and_keeps_the_daily_marker(tmp_path):
    gate = tmp_path / "power_gate.txt"
    window = pw.Window(True, 100, 200, 150, "inside")
    pw.write_gate(window, date(2026, 10, 13), gate)
    pw.write_gate(pw.Window(False, 300, 400, 350, "later"), None, gate)  # no new daily marker: keep the old one

    values = pw.read_gate(gate)
    assert values["from"] == "300" and values["until"] == "400" and values["daily_done"] == "20261013"


def test_gate_says_active_is_none_when_it_cannot_say(tmp_path):
    gate = tmp_path / "power_gate.txt"
    assert pw.gate_says_active(1000, gate) is None  # no file
    pw.write_gate(pw.Window(True, 100, 200, 150, "x"), None, gate)
    assert pw.gate_says_active(150, gate) is True
    assert pw.gate_says_active(50, gate) is False  # window not open yet
    assert pw.gate_says_active(250, gate) is None  # window passed and not refreshed: fail open


# ------------------------------------------------------------- gated decisions


def test_in_window_runs_but_respects_the_cadence(db_conn):
    now = 1_800_000_000
    _event(db_conn, 7, now + 10 * HOUR)

    assert pw.decide_gated_run(db_conn, 30, now_epoch=now, cfg=CFG).run  # first cycle in the window
    pw.record_successful_cycle(db_conn, now)
    too_soon = pw.decide_gated_run(db_conn, 30, now_epoch=now + 10 * 60, cfg=CFG)
    assert not too_soon.run and "cadence" in too_soon.reason
    assert pw.decide_gated_run(db_conn, 30, now_epoch=now + 40 * 60, cfg=CFG).run


def test_outside_window_runs_once_a_day(db_conn):
    now = int(datetime(2026, 10, 13, 8, 0).timestamp())
    _event(db_conn, 7, now + 100 * HOUR)

    first = pw.decide_gated_run(db_conn, 360, now_epoch=now, cfg=CFG)
    assert first.run and "daily run" in first.reason
    pw.record_successful_cycle(db_conn, now)

    assert not pw.decide_gated_run(db_conn, 360, now_epoch=now + 5 * HOUR, cfg=CFG).run
    next_day = int((datetime(2026, 10, 14, 8, 0)).timestamp())
    assert pw.decide_gated_run(db_conn, 360, now_epoch=next_day, cfg=CFG).run


def test_daily_run_waits_for_a_fullscreen_game_but_not_forever(db_conn):
    now = int(datetime(2026, 10, 13, 8, 0).timestamp())
    _event(db_conn, 7, now + 100 * HOUR)
    pw.record_successful_cycle(db_conn, now - 20 * HOUR)  # last good run yesterday

    deferred = pw.decide_gated_run(db_conn, 360, now_epoch=now, fullscreen=True, cfg=CFG)
    assert not deferred.run and "fullscreen" in deferred.reason

    pw.record_successful_cycle(db_conn, now - 40 * HOUR)  # older than force_after_hours (36)
    assert pw.decide_gated_run(db_conn, 360, now_epoch=now, fullscreen=True, cfg=CFG).run


# ----------------------------------------------------------------- live fixtures


def test_a_played_fixture_fpl_has_not_finished_is_not_live(db_conn):
    """FPL kept fixtures.finished = 0 for days after the whistle; that pinned
    every cadence and 'live event' lookup at live for a whole week."""
    from test_table_payload import _fixture, _seed

    _seed(db_conn, budget_tenths=950, club_limit=4)
    _fixture(db_conn, 1, 1, 1, 2, 1, 0)
    kickoff = (datetime.utcnow() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db_conn.execute("UPDATE fixtures SET finished = 0, started = 1, kickoff_time = ? WHERE id = 1", (kickoff,))
    db_conn.commit()
    assert current_live_event(db_conn) == 1  # an hour in, genuinely live

    old = (datetime.utcnow() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db_conn.execute("UPDATE fixtures SET kickoff_time = ? WHERE id = 1", (old,))
    db_conn.commit()
    assert current_live_event(db_conn) is None  # three days on, whatever FPL still says


# ----------------------------------------------------------- dashboard server


def _bare_server(power_gating=True):
    server = LiveServer.__new__(LiveServer)
    server.broadcaster = Broadcaster()
    server.activity = ActivityTracker()
    server.power_gating = power_gating
    return server


def _gate(tmp_path, monkeypatch, active):
    gate = tmp_path / "power_gate.txt"
    now = time.time()
    window = pw.Window(active, int(now - 100) if active else int(now + 5000), int(now + 10_000), None, "t")
    pw.write_gate(window, None, gate)
    monkeypatch.setattr(pw, "gate_path", lambda: gate)


def test_idle_server_stops_refreshing_outside_the_window(tmp_path, monkeypatch):
    _gate(tmp_path, monkeypatch, active=False)
    server = _bare_server()
    assert server.refresh_allowed()  # just started: someone launched it
    server.activity._last -= 30 * 60
    assert not server.refresh_allowed()  # 30 idle minutes, nobody there
    server.broadcaster.register()
    assert server.refresh_allowed()  # an open tab holds the SSE stream


def test_server_keeps_refreshing_inside_the_window_and_without_gating(tmp_path, monkeypatch):
    _gate(tmp_path, monkeypatch, active=True)
    server = _bare_server()
    server.activity._last -= 5 * 3600
    assert server.refresh_allowed()
    assert _bare_server(power_gating=False).refresh_allowed()


def test_idle_server_exits_only_outside_the_window(tmp_path, monkeypatch):
    server = _bare_server()
    server.activity._last -= 60 * 60

    _gate(tmp_path, monkeypatch, active=False)
    assert server.should_exit_idle(30)
    assert not server.should_exit_idle(None)

    _gate(tmp_path, monkeypatch, active=True)
    assert not server.should_exit_idle(30)  # the window is open: stay up

    server.broadcaster.register()
    _gate(tmp_path, monkeypatch, active=False)
    assert not server.should_exit_idle(30)  # a tab is open


def test_a_gate_that_cannot_say_never_lets_the_server_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(pw, "gate_path", lambda: tmp_path / "missing.txt")
    server = _bare_server()
    server.activity._last -= 5 * 3600
    assert not server.should_exit_idle(30)
    assert server.refresh_allowed()


# --------------------------------------------------------- the gameweek's matches


def _fixture(conn, fixture_id, event, kickoff_epoch):
    _seed_two_players_two_teams(conn)
    conn.execute(
        "INSERT INTO fixtures (id, code, event, kickoff_time, team_h, team_a, finished, started, updated_at) "
        "VALUES (?, ?, ?, ?, 1, 2, 0, 0, 't0')",
        (fixture_id, fixture_id, event, datetime.utcfromtimestamp(kickoff_epoch).strftime("%Y-%m-%dT%H:%M:%SZ")),
    )
    conn.commit()


def test_window_stays_open_through_a_friday_to_monday_gameweek(db_conn):
    deadline = 1_800_000_000
    _event(db_conn, 7, deadline)
    _event(db_conn, 8, deadline + 7 * 24 * HOUR)
    for i, offset in enumerate([2, 5, 29, 31, 53, 76, 100]):
        _fixture(db_conn, i + 1, 7, deadline + offset * HOUR)
    _fixture(db_conn, 20, 8, deadline + 7 * 24 * HOUR + 2 * HOUR)

    for hours in (4, 20, 28, 60, 90, 100.5, 102.5):
        window = pw.compute_window(db_conn, deadline + hours * HOUR, CFG)
        assert window.active, hours
    after = pw.compute_window(db_conn, deadline + 104.5 * HOUR, CFG)
    assert not after.active
    assert after.start_epoch == deadline + 7 * 24 * HOUR - 24 * HOUR


def test_a_postponed_fixture_weeks_later_does_not_hold_the_window_open(db_conn):
    deadline = 1_800_000_000
    _event(db_conn, 7, deadline)
    _fixture(db_conn, 1, 7, deadline + 2 * HOUR)
    _fixture(db_conn, 2, 7, deadline + 40 * 24 * HOUR)

    assert not pw.compute_window(db_conn, deadline + 10 * HOUR, CFG).active
    assert pw.compute_window(db_conn, deadline + 40 * 24 * HOUR, CFG).active


def test_window_covers_the_hour_before_kickoff_and_three_after(db_conn):
    kickoff = 1_800_000_000
    _event(db_conn, 7, kickoff + 90 * 24 * HOUR)
    _fixture(db_conn, 1, 7, kickoff)
    assert pw.compute_window(db_conn, kickoff - 59 * 60, CFG).active
    assert pw.compute_window(db_conn, kickoff + 2.9 * HOUR, CFG).active
    assert not pw.compute_window(db_conn, kickoff + 3.1 * HOUR, CFG).active
    assert not pw.compute_window(db_conn, kickoff - 2 * HOUR, CFG).active


def test_a_match_the_feed_reports_live_keeps_the_window_open_whatever_the_kickoff_times_say(db_conn):
    now = 1_800_000_000
    _event(db_conn, 9, now + 20 * 24 * HOUR)
    assert not pw.compute_window(db_conn, now, CFG).active
    _seed_two_players_two_teams(db_conn)
    db_conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, kickoff_utc, home_team_id, away_team_id, status, retrieved_at) "
        "VALUES (1, 'f', 'k', 1, 2, 'LIVE', ?)", (datetime.utcfromtimestamp(now - 600).isoformat() + "+00:00",),
    )
    db_conn.commit()
    window = pw.compute_window(db_conn, now, CFG)
    assert window.active and "matches in play" in window.reason
    assert window.until_epoch >= now + 3 * HOUR


def test_a_live_row_from_yesterday_does_not_hold_the_window_open(db_conn):
    now = 1_800_000_000
    _event(db_conn, 9, now + 20 * 24 * HOUR)
    _seed_two_players_two_teams(db_conn)
    db_conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, kickoff_utc, home_team_id, away_team_id, status, retrieved_at) "
        "VALUES (1, 'f', 'k', 1, 2, 'LIVE', ?)", (datetime.utcfromtimestamp(now - 30 * HOUR).isoformat() + "+00:00",),
    )
    db_conn.commit()
    assert not pw.compute_window(db_conn, now, CFG).active
