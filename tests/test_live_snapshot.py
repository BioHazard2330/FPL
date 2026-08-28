import json

from fpl_agent.database.decisions import log_decision
from fpl_agent.monitoring.live_snapshot import build_live_snapshot, write_live_snapshot
from fpl_agent.optimization.locked_squad import LockedSquadState
from fpl_agent.optimization.squad import PlayerCandidate, StartingXI


def _seed_event(conn, event_id=2, is_next=1, deadline_epoch=99999999999):
    conn.execute(
        "INSERT INTO events (id, name, deadline_time, deadline_time_epoch, finished, is_previous, "
        "is_current, is_next, average_entry_score, highest_score, updated_at) VALUES "
        "(?,?,'t0',?,0,0,0,?,NULL,NULL,'t0')",
        (event_id, f"Gameweek {event_id}", deadline_epoch, is_next),
    )
    conn.commit()


def test_build_live_snapshot_has_no_rank_or_points_without_any_data(db_conn):
    _seed_event(db_conn)
    snap = build_live_snapshot(db_conn, live_payload=None)
    assert snap["rank"] is None
    assert snap["points"] is None
    assert snap["version"]  # a real, non-empty version stamp


def test_build_live_snapshot_reads_the_latest_live_rank_decision(db_conn):
    _seed_event(db_conn)
    log_decision(
        db_conn, "live_rank", summary="LiveFPL: rank ~123,456",
        detail={"source": "livefpl", "estimated_rank": 123456, "precision": "exact", "event": 2},
        confidence="high",
    )
    snap = build_live_snapshot(db_conn, live_payload=None)
    assert snap["rank"]["estimated_rank"] == 123456
    assert snap["rank"]["source"] == "livefpl"
    assert snap["rank"]["is_current"] is True  # event=2 matches the live/reference event


def test_build_live_snapshot_flags_a_stale_rank_as_not_current(db_conn):
    _seed_event(db_conn, event_id=2)
    _seed_event(db_conn, event_id=1, is_next=0)
    log_decision(
        db_conn, "live_rank", summary="stale GW1 rank",
        detail={"source": "livefpl", "estimated_rank": 999, "precision": "exact", "event": 1},
        confidence="high",
    )
    snap = build_live_snapshot(db_conn, live_payload=None)
    # A GW1 rank decision must never be presented as GW2's current rank -
    # same rule the dashboard's own rank tile already enforces.
    assert snap["rank"]["is_current"] is False


def test_write_live_snapshot_writes_real_json_to_disk(db_conn, tmp_path, monkeypatch):
    import fpl_agent.monitoring.live_snapshot as ls_mod

    target = tmp_path / "live_snapshot.json"
    monkeypatch.setattr(ls_mod, "SNAPSHOT_PATH", target)
    monkeypatch.setattr(ls_mod, "DATA_DIR", tmp_path)

    _seed_event(db_conn)
    path = write_live_snapshot(db_conn, live_payload=None)

    assert path == target
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["event"] == 2


def test_write_live_snapshot_never_fabricates_points_without_a_locked_squad(db_conn):
    _seed_event(db_conn)
    snap = build_live_snapshot(db_conn, live_payload={"elements": []})
    assert snap["points"] is None


def _seed_player(conn, player_id, web_name="Salah", status="a", team_id=1, element_type=3):
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?, 't0')",
        (team_id, team_id, f"Team{team_id}", f"T{team_id}"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO element_types (id, singular_name, singular_name_short, plural_name, updated_at) "
        "VALUES (?,?,?,?, 't0')",
        (element_type, "Midfielder", "MID", "Midfielders"),
    )
    conn.execute(
        "INSERT INTO players (id, code, web_name, team_id, element_type, status, removed, updated_at) "
        "VALUES (?,?,?,?,?,?,0,'t0')",
        (player_id, player_id, web_name, team_id, element_type, status),
    )
    conn.commit()


def _fake_locked_squad(event, starting_ids, bench_ids=(), captain_id=None, vice_id=None):
    def cand(pid):
        return PlayerCandidate(
            player_id=pid, web_name=f"P{pid}", position="MID", team_id=1, team_short="T1",
            price_tenths=80, xp=5.5, median=5.5, floor=2.0, ceiling=9.0, confidence="high", expected_minutes=90.0,
        )

    starting = [cand(pid) for pid in starting_ids]
    bench = [cand(pid) for pid in bench_ids]
    xi = StartingXI(
        starting=starting, bench=bench,
        captain=next((c for c in starting if c.player_id == captain_id), None),
        vice_captain=next((c for c in starting if c.player_id == vice_id), None),
    )
    return LockedSquadState(
        source="synced_real", event=event, squad_ids=frozenset(list(starting_ids) + list(bench_ids)),
        xi=xi, bank_tenths=10, squad_value_tenths=1000, decision_id=None, free_transfers=1,
    )


def test_squad_block_reports_slot_captain_and_availability(db_conn, monkeypatch):
    import fpl_agent.monitoring.live_snapshot as ls_mod

    _seed_event(db_conn)
    _seed_player(db_conn, 1, web_name="Haaland", status="a")
    _seed_player(db_conn, 2, web_name="Salah", status="i")
    locked = _fake_locked_squad(2, starting_ids=[1], bench_ids=[2], captain_id=1)
    monkeypatch.setattr(ls_mod, "get_locked_squad", lambda conn: locked)

    snap = build_live_snapshot(db_conn, live_payload=None)
    squad = {row["player_id"]: row for row in snap["squad"]}
    assert squad[1]["slot"] == "starting"
    assert squad[1]["is_captain"] is True
    assert squad[1]["xp"] == 5.5
    assert squad[2]["slot"] == "bench"
    # A confirmed-injured player must never be silently reported as fine.
    assert squad[2]["classification"] in ("CONFIRMED UNAVAILABLE", "LIKELY UNAVAILABLE", "DOUBTFUL")


def test_squad_block_empty_without_a_locked_squad(db_conn, monkeypatch):
    import fpl_agent.monitoring.live_snapshot as ls_mod

    _seed_event(db_conn)
    monkeypatch.setattr(ls_mod, "get_locked_squad", lambda conn: None)
    snap = build_live_snapshot(db_conn, live_payload=None)
    assert snap["squad"] == []


def test_match_events_and_bonus_defcon_share_one_live_bonus_computation(db_conn, monkeypatch):
    import fpl_agent.monitoring.live_snapshot as ls_mod

    _seed_event(db_conn)
    _seed_player(db_conn, 1, web_name="Haaland")
    locked = _fake_locked_squad(2, starting_ids=[1])
    monkeypatch.setattr(ls_mod, "get_locked_squad", lambda conn: locked)

    live_payload = {
        "elements": [
            {
                "id": 1,
                "stats": {"minutes": 90, "goals_scored": 2, "assists": 1, "bps": 40, "bonus": 0, "red_cards": 0},
                "explain": [{"fixture": 100}],
            }
        ]
    }
    snap = build_live_snapshot(db_conn, live_payload=live_payload)
    assert snap["bonus_defcon"][0]["player_id"] == 1
    events = {(e["player_id"], e["kind"]): e["count"] for e in snap["match_events"]}
    assert events[(1, "goal")] == 2
    assert events[(1, "assist")] == 1


def test_source_freshness_block_flags_degraded_sources(db_conn):
    conn = db_conn
    conn.execute(
        "INSERT INTO source_health (source_name, last_success, last_failure, failure_count) "
        "VALUES ('odds_api', 't1', 't2', 16)"
    )
    conn.execute(
        "INSERT INTO source_health (source_name, last_success, failure_count) "
        "VALUES ('fpl_api_bootstrap', 't1', 0)"
    )
    conn.commit()
    _seed_event(conn)
    snap = build_live_snapshot(conn, live_payload=None)
    by_name = {r["source"]: r for r in snap["source_freshness"]}
    assert by_name["odds_api"]["degraded"] is True
    assert by_name["fpl_api_bootstrap"]["degraded"] is False


def test_gw_block_reports_real_lifecycle_state(db_conn):
    _seed_event(db_conn)
    snap = build_live_snapshot(db_conn, live_payload=None)
    assert snap["gw"]["event"] == 2
    # No fixtures seeded for GW2 -> lifecycle can't classify, honest None/UNKNOWN, never fabricated.
    assert snap["gw"]["state"] in (None, "UNKNOWN")


def test_cadence_block_reports_real_derived_interval_and_last_sync(db_conn):
    _seed_event(db_conn)
    db_conn.execute(
        "INSERT INTO source_health (source_name, last_success, failure_count) "
        "VALUES ('fpl_api_bootstrap', '2026-08-29T10:00:00+00:00', 0)"
    )
    db_conn.commit()
    snap = build_live_snapshot(db_conn, live_payload=None)
    cadence = snap["cadence"]
    assert cadence["system"]["last_sync_at"] == "2026-08-29T10:00:00+00:00"
    assert cadence["system"]["interval_minutes"] > 0
    assert cadence["system"]["reason"]  # a real, non-empty explanation, never blank
    assert cadence["rank"]["next_due_floor_minutes"] >= 5  # LiveFPL's own real minimum


def test_decision_status_is_recomputing_while_a_real_auto_trigger_lock_is_fresh(db_conn):
    from datetime import datetime, timezone

    from fpl_agent.monitoring.live_snapshot import _decision_status

    now = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('strategic_plan_auto_started_at', ?, ?)",
        (now, now),
    )
    db_conn.commit()
    assert _decision_status(db_conn, is_stale=False) == "RECOMPUTING"


def test_decision_status_ignores_a_stale_abandoned_recompute_lock(db_conn):
    from datetime import datetime, timedelta, timezone

    from fpl_agent.monitoring.live_snapshot import _decision_status

    old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('strategic_plan_auto_started_at', ?, ?)",
        (old, old),
    )
    db_conn.commit()
    # A 30min-old lock is a real, abandoned/crashed prior run - must fall
    # back to the real freshness signal, never claim RECOMPUTING forever.
    assert _decision_status(db_conn, is_stale=False) == "CURRENT"
    assert _decision_status(db_conn, is_stale=True) == "STALE"


def test_decision_status_current_and_stale_without_any_lock(db_conn):
    from fpl_agent.monitoring.live_snapshot import _decision_status

    assert _decision_status(db_conn, is_stale=False) == "CURRENT"
    assert _decision_status(db_conn, is_stale=True) == "STALE"
    assert _decision_status(db_conn, is_stale=None) == "UNKNOWN"


def test_points_changes_block_none_when_no_gameweek_finished(db_conn):
    _seed_event(db_conn, event_id=1, is_next=0)
    snap = build_live_snapshot(db_conn, live_payload=None)
    assert snap["points_changes"] is None


def test_points_changes_block_reports_real_revision_count(db_conn):
    from fpl_agent.monitoring.live_snapshot import _points_changes_block

    db_conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (1,'GW1','t0',1,1,0,0,0,'t0')"
    )
    db_conn.execute(
        "INSERT INTO teams (id,code,name,short_name,strength_overall_home,strength_overall_away,"
        "strength_attack_home,strength_attack_away,strength_defence_home,strength_defence_away,pulse_id,updated_at) "
        "VALUES (1,1,'T1','T1',3,3,0,0,0,0,1,'t0'), (2,2,'T2','T2',3,3,0,0,0,0,2,'t0')"
    )
    db_conn.execute(
        "INSERT INTO element_types (id,singular_name,singular_name_short,plural_name,squad_min_play,"
        "squad_max_play,squad_select,updated_at) VALUES (2,'Defender','DEF','Defenders',3,5,5,'t0')"
    )
    db_conn.execute(
        "INSERT INTO players (id,code,web_name,team_id,element_type,status,removed,updated_at) "
        "VALUES (1,1,'D1',1,2,'a',0,'t0')"
    )
    db_conn.execute(
        "INSERT INTO fixtures (id,code,event,kickoff_time,team_h,team_a,team_h_score,team_a_score,"
        "finished,started,updated_at) VALUES (1,1,1,'2026-08-21T19:00:00Z',1,2,1,0,1,1,'t0')"
    )
    for ts, bonus, dc in (("2026-08-21T21:45:00Z", 1, 0), ("2026-08-22T09:00:00Z", 3, 0)):
        db_conn.execute(
            "INSERT INTO player_stats_snapshot (player_id, retrieved_at, stats_hash, bonus, defensive_contribution) "
            "VALUES (1, ?, ?, ?, ?)",
            (ts, ts, bonus, dc),
        )
    db_conn.commit()

    block = _points_changes_block(db_conn, frozenset({1}))

    assert block["event"] == 1
    assert block["total_revisions"] == 1
    assert block["squad_revisions"] == 1
    assert block["locked"] is True
