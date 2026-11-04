import json
import logging
from datetime import datetime, timedelta, timezone

from fpl_agent.models import self_check as sc
from fpl_agent.scheduler import run_ledger as rl


class _Keep:
    """Hands out the test connection and ignores close()."""

    def __init__(self, conn):
        self.conn = conn

    def __call__(self):
        return self

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def close(self):
        pass


def _log(level, text):
    logger = logging.getLogger("fpl_agent.scheduler")
    logger.setLevel(logging.INFO)
    logger.log(level, text)


def test_a_cycle_is_recorded_with_its_steps_and_errors(db_conn, tmp_path):
    with rl.record_run(False, tmp_path, _Keep(db_conn)):
        _log(logging.INFO, "run-scheduled sync ok")
        _log(logging.ERROR, "run-scheduled xg backfill failed - not fatal")
        _log(logging.INFO, "run-scheduled week plan rebuilt")
    r = db_conn.execute("SELECT * FROM pipeline_run").fetchone()
    assert r["status"] == "errors" and r["errors"] == 1
    assert [s["text"] for s in json.loads(r["steps"])][0] == "sync ok"
    assert not (tmp_path / rl.JOURNAL).exists()


def test_a_cycle_that_decided_not_to_run_records_nothing(db_conn, tmp_path):
    with rl.record_run(True, tmp_path, _Keep(db_conn)):
        _log(logging.INFO, "run-scheduled (gated) skipped: outside window")
    assert db_conn.execute("SELECT COUNT(*) FROM pipeline_run").fetchone()[0] == 0


def test_a_journal_left_behind_is_recorded_as_a_killed_cycle_and_alerts(db_conn, tmp_path):
    rows = [{"t": 1000.0, "level": "INFO", "text": "sync ok"}, {"t": 1600.0, "level": "INFO", "text": "week plan"}]
    (tmp_path / rl.JOURNAL).write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    with rl.record_run(False, tmp_path, _Keep(db_conn)):
        pass
    r = db_conn.execute("SELECT status, seconds FROM pipeline_run").fetchone()
    assert r["status"] == "killed" and r["seconds"] == 600.0
    assert db_conn.execute("SELECT COUNT(*) FROM change_events WHERE event_type = 'daemon_failing'").fetchone()[0] == 1


def test_a_step_failing_three_cycles_running_alerts_once_a_day(db_conn):
    now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
    for i in range(3):
        rl._write(db_conn, 1000.0 + i, 1001.0 + i, "errors", True, [{"t": 1000.0, "level": "ERROR", "text": f"xg backfill failed run {i}"}])
    assert rl.failing_steps(db_conn) == ["xg backfill failed run #"]
    assert rl.alert_failures(db_conn, now) == 1
    assert rl.alert_failures(db_conn, now + timedelta(hours=2)) == 0


def test_a_step_that_recovered_is_not_failing(db_conn):
    for text, level in (("x failed", "ERROR"), ("x failed", "ERROR"), ("x ok", "INFO")):
        rl._write(db_conn, 1000.0, 1001.0, "ok", True, [{"t": 1000.0, "level": level, "text": text}])
    assert rl.failing_steps(db_conn) == []


def test_every_check_answers_on_an_empty_database(db_conn):
    checks = sc.run_checks(db_conn, datetime(2026, 11, 4, tzinfo=timezone.utc))
    assert len(checks) == len(sc.CHECKS)
    assert all(not c["detail"].startswith("the check itself failed") for c in checks), [c for c in checks if "itself" in c["detail"]]


def test_a_failing_act_check_alerts_when_it_starts_failing_and_not_again(db_conn):
    now = datetime(2026, 11, 4, tzinfo=timezone.utc)
    sc.store_checks(db_conn, now)
    n = db_conn.execute("SELECT COUNT(*) FROM change_events WHERE event_type = 'self_check'").fetchone()[0]
    assert n >= 1
    sc.store_checks(db_conn, now + timedelta(hours=1))
    assert db_conn.execute("SELECT COUNT(*) FROM change_events WHERE event_type = 'self_check'").fetchone()[0] == n


def test_a_feed_off_its_usual_grid_is_caught(db_conn):
    now = datetime(2026, 11, 4, tzinfo=timezone.utc)
    db_conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'A','AAA','t')")
    db_conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (1,'F','FWD','Fs','t')")
    for pid, minutes in enumerate((87, 63, 12, 45), start=1):
        db_conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (?,?,?,1,1,'a',0,'t')", (pid, pid, f"P{pid}"))
        db_conn.execute("INSERT INTO player_start_probability_history (player_id, team_id, start_percent, fetched_at) VALUES (?,1,?,?)", (pid, minutes, now.isoformat()))
    ok, detail = sc.start_feed(db_conn, now)
    assert not ok and "grid" in detail


def _momentum(conn, pid, stamps):
    for t in stamps:
        conn.execute("INSERT INTO player_transfer_momentum_history (player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from, valid_until) "
                     "VALUES (?,0,0,0,0,?,'x')", (pid, t))


def test_thinning_keeps_what_the_price_model_reads_each_night(db_conn):
    from fpl_agent.monitoring.cleanup import thin_momentum

    db_conn.execute("INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'A','AAA','t')")
    db_conn.execute("INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) VALUES (1,'F','FWD','Fs','t')")
    db_conn.execute("INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) VALUES (1,1,'P',1,1,'a',0,'t')")
    day = "2026-09-01T"
    _momentum(db_conn, 1, [day + h for h in ("00:15:00+00:00", "02:15:00+00:00", "02:45:00+00:00", "03:15:00+00:00", "09:00:00+00:00", "23:00:00+00:00")])
    _momentum(db_conn, 1, ["2026-11-03T09:00:00+00:00", "2026-11-03T09:15:00+00:00"])
    db_conn.execute("INSERT INTO player_transfer_momentum_history (player_id, transfers_in_event, transfers_out_event, transfers_in, transfers_out, valid_from, valid_until) VALUES (1,0,0,0,0,'2026-08-01T09:00:00+00:00',NULL)")
    assert thin_momentum(db_conn, datetime(2026, 11, 4, tzinfo=timezone.utc)) == 3
    left = {r[0][11:16] for r in db_conn.execute("SELECT valid_from FROM player_transfer_momentum_history WHERE valid_from LIKE '2026-09-01%'")}
    assert left == {"02:15", "03:15", "23:00"}
    assert db_conn.execute("SELECT COUNT(*) FROM player_transfer_momentum_history WHERE valid_from LIKE '2026-11-03%'").fetchone()[0] == 2
    assert db_conn.execute("SELECT COUNT(*) FROM player_transfer_momentum_history WHERE valid_until IS NULL").fetchone()[0] == 1
