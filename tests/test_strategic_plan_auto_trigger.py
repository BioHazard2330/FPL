"""Real regression coverage for the P0 "optimizer must run automatically" fix
(2026-08-29, master automation pass) - `_maybe_trigger_strategic_plan_recompute`
fires a real `fpl strategic-plan` as a detached background subprocess only when
a real material change (the same HIGH-severity `change_events` bar
`models.decision_freshness`/`optimization.post_gw_pipeline` already use) has
happened since the last cached decision, or none has ever been logged - never
on every scheduled cycle regardless of whether anything actually changed."""
import subprocess
from datetime import datetime, timedelta, timezone

import fpl_agent.cli.main as main_mod
import fpl_agent.optimization.locked_squad as locked_squad_mod
from fpl_agent.database.decisions import log_decision
from fpl_agent.ingestion.change_detection import record_event
from fpl_agent.optimization.locked_squad import LockedSquadState
from fpl_agent.optimization.squad import PlayerCandidate, StartingXI


def _candidate(pid):
    return PlayerCandidate(
        player_id=pid, web_name=f"P{pid}", position="MID", team_id=1, team_short="T1",
        price_tenths=50, xp=4.0, median=4.0, floor=2.0, ceiling=6.0, confidence="MEDIUM", expected_minutes=80.0,
    )


def _locked(squad_ids=(1, 2, 3)):
    xi = StartingXI(starting=[_candidate(pid) for pid in squad_ids], bench=[], captain=_candidate(1), vice_captain=None)
    return LockedSquadState(
        source="synced_real", event=1, squad_ids=frozenset(squad_ids), xi=xi,
        bank_tenths=10, squad_value_tenths=500, decision_id=None,
    )


class _FakePopenCall:
    """Records the args a real subprocess.Popen call would have used,
    without ever actually spawning a real ~2-10min strategic-plan process."""
    def __init__(self):
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return object()


def test_no_locked_squad_is_a_real_noop(db_conn, monkeypatch):
    monkeypatch.setattr(locked_squad_mod, "get_locked_squad", lambda conn: None)
    fake_popen = _FakePopenCall()
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = main_mod._maybe_trigger_strategic_plan_recompute(db_conn)

    assert result is None
    assert fake_popen.calls == []


def test_triggers_when_no_strategic_plan_has_ever_been_logged(db_conn, monkeypatch, tmp_path):
    monkeypatch.setattr(locked_squad_mod, "get_locked_squad", lambda conn: _locked())
    monkeypatch.setattr(main_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(main_mod, "LOGS_DIR", tmp_path / "logs")
    fake_popen = _FakePopenCall()
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = main_mod._maybe_trigger_strategic_plan_recompute(db_conn)

    assert result == "no strategic_plan decision has ever been logged"
    assert len(fake_popen.calls) == 1
    args, kwargs = fake_popen.calls[0]
    assert args[1] == "strategic-plan"
    # Real overlap-guard marker must be written before the subprocess launches.
    lock = db_conn.execute("SELECT value FROM app_meta WHERE key='strategic_plan_auto_started_at'").fetchone()
    assert lock is not None


def test_no_trigger_when_no_material_change_since_last_plan(db_conn, monkeypatch, tmp_path):
    monkeypatch.setattr(locked_squad_mod, "get_locked_squad", lambda conn: _locked())
    monkeypatch.setattr(main_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(main_mod, "LOGS_DIR", tmp_path / "logs")
    log_decision(db_conn, "strategic_plan", "test", {})
    db_conn.commit()
    fake_popen = _FakePopenCall()
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = main_mod._maybe_trigger_strategic_plan_recompute(db_conn)

    assert result is None
    assert fake_popen.calls == []


def test_triggers_on_a_real_material_change_to_a_squad_player(db_conn, monkeypatch, tmp_path):
    monkeypatch.setattr(locked_squad_mod, "get_locked_squad", lambda conn: _locked(squad_ids=(1, 2, 3)))
    monkeypatch.setattr(main_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(main_mod, "LOGS_DIR", tmp_path / "logs")
    log_decision(db_conn, "strategic_plan", "test", {})
    db_conn.commit()
    later = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    record_event(db_conn, "status_change", "player", 1, "a", "i", later, "fpl_api", "CONFIRMED", "HIGH")
    db_conn.execute(
        "INSERT INTO teams (id, code, name, short_name, updated_at) VALUES (1,1,'T1','T1','t0')"
    )
    db_conn.execute(
        "INSERT INTO element_types (id, singular_name, singular_name_short, plural_name, squad_min_play, "
        "squad_max_play, squad_select, updated_at) VALUES (1,'Midfielder','MID','Midfielders',2,5,5,'t0')"
    )
    db_conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
        "VALUES (1,1,'Haaland',1,1,'i',0,'t0')"
    )
    db_conn.commit()
    fake_popen = _FakePopenCall()
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = main_mod._maybe_trigger_strategic_plan_recompute(db_conn)

    assert result is not None
    assert "Haaland" in result and "status_change" in result
    assert len(fake_popen.calls) == 1


def test_ignores_a_material_change_to_a_non_squad_player(db_conn, monkeypatch, tmp_path):
    monkeypatch.setattr(locked_squad_mod, "get_locked_squad", lambda conn: _locked(squad_ids=(1, 2, 3)))
    monkeypatch.setattr(main_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(main_mod, "LOGS_DIR", tmp_path / "logs")
    log_decision(db_conn, "strategic_plan", "test", {})
    db_conn.commit()
    later = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    record_event(db_conn, "status_change", "player", 999, "a", "i", later, "fpl_api", "CONFIRMED", "HIGH")
    db_conn.commit()
    fake_popen = _FakePopenCall()
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = main_mod._maybe_trigger_strategic_plan_recompute(db_conn)

    assert result is None
    assert fake_popen.calls == []


def test_triggers_when_the_locked_squad_no_longer_matches_the_last_logged_plan(db_conn, monkeypatch, tmp_path):
    """Real gap this closes: a transfer made directly in the official FPL
    app (or a chip played by hand) changes `locked.squad_ids` with no
    corresponding player-level `change_events` row - the materiality check
    alone would miss it entirely. `strategic_plan`'s own logged detail now
    carries `squad_ids`, so a real mismatch against the CURRENT locked squad
    is checked directly, independent of change_events."""
    monkeypatch.setattr(locked_squad_mod, "get_locked_squad", lambda conn: _locked(squad_ids=(1, 2, 3)))
    monkeypatch.setattr(main_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(main_mod, "LOGS_DIR", tmp_path / "logs")
    log_decision(db_conn, "strategic_plan", "test", {"squad_ids": [1, 2, 99]})  # real squad has since changed (99 -> 3)
    db_conn.commit()
    fake_popen = _FakePopenCall()
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = main_mod._maybe_trigger_strategic_plan_recompute(db_conn)

    assert result == "locked squad has changed since the last strategic plan (real transfer/chip made outside the model)"
    assert len(fake_popen.calls) == 1


def test_no_trigger_from_squad_check_when_squad_ids_were_never_logged(db_conn, monkeypatch, tmp_path):
    """An older decision logged before the `squad_ids` field existed must
    degrade to the change_events-only check, never a false trigger just
    because the field is absent."""
    monkeypatch.setattr(locked_squad_mod, "get_locked_squad", lambda conn: _locked(squad_ids=(1, 2, 3)))
    monkeypatch.setattr(main_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(main_mod, "LOGS_DIR", tmp_path / "logs")
    log_decision(db_conn, "strategic_plan", "test", {})  # no squad_ids field at all
    db_conn.commit()
    fake_popen = _FakePopenCall()
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = main_mod._maybe_trigger_strategic_plan_recompute(db_conn)

    assert result is None
    assert fake_popen.calls == []


def test_overlap_guard_skips_a_recent_prior_auto_trigger(db_conn, monkeypatch, tmp_path):
    monkeypatch.setattr(locked_squad_mod, "get_locked_squad", lambda conn: _locked())
    monkeypatch.setattr(main_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(main_mod, "LOGS_DIR", tmp_path / "logs")
    recent = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('strategic_plan_auto_started_at', ?, ?)",
        (recent, recent),
    )
    db_conn.commit()
    fake_popen = _FakePopenCall()
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = main_mod._maybe_trigger_strategic_plan_recompute(db_conn)

    assert result is None
    assert fake_popen.calls == []


def test_overlap_guard_allows_a_new_trigger_once_the_prior_lock_is_stale(db_conn, monkeypatch, tmp_path):
    monkeypatch.setattr(locked_squad_mod, "get_locked_squad", lambda conn: _locked())
    monkeypatch.setattr(main_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(main_mod, "LOGS_DIR", tmp_path / "logs")
    stale = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('strategic_plan_auto_started_at', ?, ?)",
        (stale, stale),
    )
    db_conn.commit()
    fake_popen = _FakePopenCall()
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = main_mod._maybe_trigger_strategic_plan_recompute(db_conn)

    assert result == "no strategic_plan decision has ever been logged"
    assert len(fake_popen.calls) == 1
