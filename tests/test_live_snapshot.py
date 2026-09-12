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
    assert snap["charts"] is None  # no real team synced - never a fabricated empty chart


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


def test_build_live_snapshot_carries_real_livefpl_rank_change_fields(db_conn):
    """Real gap found 2026-09-12 (direct user comparison against
    livefpl.net) - the LiveFPL connector already fetches old_rank/rank_gain/
    change_pct/safety_score/template_pct/chip_played every refresh, but the
    live snapshot dropped every one of them before this fix."""
    _seed_event(db_conn)
    log_decision(
        db_conn, "live_rank", summary="LiveFPL: rank ~123,456",
        detail={
            "source": "livefpl", "estimated_rank": 123456, "precision": "exact", "event": 2,
            "old_rank": 1589046, "rank_gain": 808515, "change_pct": 50.88,
            "safety_score": 15.0, "template_pct": 80.0, "chip_played": None, "gw_rank": 45211,
        },
        confidence="high",
    )
    snap = build_live_snapshot(db_conn, live_payload=None)
    assert snap["rank"]["old_rank"] == 1589046
    assert snap["rank"]["rank_gain"] == 808515
    assert snap["rank"]["change_pct"] == 50.88
    assert snap["rank"]["safety_score"] == 15.0
    assert snap["rank"]["template_pct"] == 80.0
    assert snap["rank"]["gw_rank"] == 45211


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


def _fake_locked_squad(event, starting_ids, bench_ids=(), captain_id=None, vice_id=None, source="synced_real"):
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
        source=source, event=event, squad_ids=frozenset(list(starting_ids) + list(bench_ids)),
        xi=xi, bank_tenths=10, squad_value_tenths=1000, decision_id=None, free_transfers=1,
    )


def _seed_live_match(conn, match_id_hint, home_team_id, away_team_id, status="LIVE"):
    for team_id in (home_team_id, away_team_id):
        conn.execute(
            "INSERT OR IGNORE INTO teams (id, code, name, short_name, updated_at) VALUES (?,?,?,?, 't0')",
            (team_id, team_id, f"Team{team_id}", f"T{team_id}"),
        )
    conn.execute(
        "INSERT INTO match_intelligence (id, fotmob_match_id, home_team_id, away_team_id, status, "
        "home_score, away_score, live_minute, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (match_id_hint, str(match_id_hint), home_team_id, away_team_id, status, 1, 0, "24'", "2026-08-29T18:24:00+00:00"),
    )
    conn.execute(
        "INSERT INTO team_match_state (match_id, team_id, possession_pct, shots, shots_on_target, xg, corners, "
        "big_chances, big_chances_missed, yellow_cards, red_cards, formation, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (match_id_hint, home_team_id, 45.0, 6, 2, 0.8, 3, 1, 1, 2, 0, "4-3-3", "2026-08-29T18:24:00+00:00"),
    )
    conn.execute(
        "INSERT INTO team_match_state (match_id, team_id, possession_pct, shots, shots_on_target, xg, corners, "
        "big_chances, big_chances_missed, yellow_cards, red_cards, formation, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (match_id_hint, away_team_id, 55.0, 8, 4, 1.4, 5, 2, 0, 1, 1, "4-2-3-1", "2026-08-29T18:24:00+00:00"),
    )
    conn.execute(
        "INSERT INTO match_momentum (match_id, minute, value, retrieved_at) VALUES (?,?,?,?), (?,?,?,?)",
        (match_id_hint, 0, 0, "2026-08-29T18:24:00+00:00", match_id_hint, 24, -35, "2026-08-29T18:24:00+00:00"),
    )
    conn.execute(
        "INSERT INTO match_shots (match_id, fotmob_shot_id, team_id, player_name, minute, x, y, xg, "
        "is_on_target, outcome, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (match_id_hint, "s1", home_team_id, "Test Scorer", 12, 88.0, 50.0, 0.3, 1, "Goal", "2026-08-29T18:24:00+00:00"),
    )
    conn.commit()


def test_active_matches_block_reads_real_match_data_no_extra_network(db_conn):
    from fpl_agent.monitoring.live_snapshot import _active_matches_block

    _seed_player(db_conn, 1, web_name="Haaland", team_id=10, element_type=4)
    _seed_live_match(db_conn, 500, home_team_id=10, away_team_id=20)
    conn = db_conn
    conn.execute(
        "INSERT INTO player_match_state (match_id, player_id, fotmob_player_id, team_id, started, minutes, "
        "rating, goals, assists, shots, xg, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (500, 1, "999", 10, 1, 24, 7.9, 1, 0, 2, 0.31, "2026-08-29T18:24:00+00:00"),
    )
    conn.commit()

    active = _active_matches_block(conn, frozenset({1}))
    assert len(active) == 1
    m = active[0]
    assert m["is_squad_match"] is True
    assert m["home_score"] == 1 and m["away_score"] == 0
    assert m["live_minute"] == "24'"
    assert m["team_stats"]["home"]["possession_pct"] == 45.0
    assert m["team_stats"]["away"]["big_chances"] == 2
    assert m["team_stats"]["home"]["yellow_cards"] == 2 and m["team_stats"]["home"]["red_cards"] == 0
    assert m["team_stats"]["away"]["red_cards"] == 1
    assert m["team_stats"]["home"]["formation"] == "4-3-3"
    assert [(p["minute"], p["value"]) for p in m["momentum"]] == [(0, 0), (24, -35)]
    assert m["shots"][0]["outcome"] == "Goal"
    assert len(m["my_players"]) == 1
    assert m["my_players"][0]["web_name"] == "Haaland"
    assert m["my_players"][0]["rating"] == 7.9


def test_active_matches_block_win_probability_none_without_a_real_fitted_model(db_conn):
    """`_seed_live_match` seeds no `match_results_history` at all, so the
    real Dixon-Coles model genuinely can't fit - the field must come back
    `None`, never a guessed 50/50, for a real live match with insufficient
    league-wide history (true for every early-season match this session)."""
    from fpl_agent.monitoring.live_snapshot import _active_matches_block

    _seed_live_match(db_conn, 500, home_team_id=10, away_team_id=20)
    active = _active_matches_block(db_conn, frozenset())
    assert active[0]["win_probability"] is None


def test_active_matches_block_win_probability_real_when_model_available(db_conn, monkeypatch):
    from fpl_agent.monitoring.live_snapshot import _active_matches_block
    import fpl_agent.models.expected_points as expected_points_mod
    from fpl_agent.ingestion.market_identity import get_or_create_market_team
    from fpl_agent.models.team_strength_dc import DixonColesModel, TeamStrength

    _seed_live_match(db_conn, 500, home_team_id=10, away_team_id=20)
    home_market = get_or_create_market_team(db_conn, "fpl", "Team10")
    away_market = get_or_create_market_team(db_conn, "fpl", "Team20")
    model = DixonColesModel(
        teams={home_market: TeamStrength(home_market, 0.2, -0.1), away_market: TeamStrength(away_market, -0.1, 0.1)},
        home_advantage=0.2, rho=0.0, reference_team_id=away_market,
    )
    monkeypatch.setattr(expected_points_mod, "_get_or_fit_dc_model", lambda conn, as_of_date: model)

    active = _active_matches_block(db_conn, frozenset())
    wp = active[0]["win_probability"]
    assert wp is not None
    # Real seeded state: 1-0 at minute 24 (see _seed_live_match) - the
    # leading side must read as favoured, not a coin flip.
    assert wp["home_win_pct"] > wp["away_win_pct"]
    assert "basis" in wp


def test_parse_live_minute_reads_real_fotmob_display_strings():
    from fpl_agent.monitoring.live_snapshot import _parse_live_minute

    assert _parse_live_minute("24'") == 24.0
    assert _parse_live_minute("45+2'") == 47.0
    assert _parse_live_minute("HT") == 45.0
    assert _parse_live_minute(None) is None
    assert _parse_live_minute("garbage") is None


def test_active_matches_block_sorts_squad_matches_first(db_conn):
    from fpl_agent.monitoring.live_snapshot import _active_matches_block

    _seed_player(db_conn, 1, web_name="Haaland", team_id=10, element_type=4)
    _seed_live_match(db_conn, 500, home_team_id=30, away_team_id=40)  # no squad player
    _seed_live_match(db_conn, 501, home_team_id=10, away_team_id=20)  # has a squad player (team 10)

    active = _active_matches_block(db_conn, frozenset({1}))
    assert len(active) == 2
    assert active[0]["match_id"] == 501
    assert active[0]["is_squad_match"] is True
    assert active[1]["is_squad_match"] is False


def test_active_matches_block_empty_when_no_live_match(db_conn):
    from fpl_agent.monitoring.live_snapshot import _active_matches_block

    assert _active_matches_block(db_conn, frozenset()) == []


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


def test_points_block_carries_real_per_player_points_and_multiplier(db_conn, monkeypatch):
    """Real fix (2026-08-28, direct user ask: "the Live Tracking table
    should patch player rows from the live snapshot instead of waiting for
    a full reload") - the browser needs a per-player breakdown to patch
    each row; this is the canonical snapshot's own source of that data
    (`_MyLiveScore.by_player`, single computation, no second live-data
    path). Captain gets the real 2x multiplier, a plain starter gets 1x, a
    bench player (not in the fallback `picks` list at all) gets 0x -
    matches the SAME real semantics `points`/`captain_points` above it
    already use, just exposed per-player instead of only aggregated."""
    import fpl_agent.monitoring.live_snapshot as ls_mod

    _seed_event(db_conn)
    _seed_player(db_conn, 1, web_name="Haaland")
    _seed_player(db_conn, 2, web_name="Salah")
    _seed_player(db_conn, 3, web_name="Sub", team_id=1)
    locked = _fake_locked_squad(2, starting_ids=[1, 2], bench_ids=[3], captain_id=1, source="locked_decision")
    monkeypatch.setattr(ls_mod, "get_locked_squad", lambda conn: locked)

    live_payload = {
        "elements": [
            {"id": 1, "stats": {"minutes": 90, "goals_scored": 2, "assists": 0, "bps": 40, "bonus": 0, "total_points": 12}, "explain": [{"fixture": 100}]},
            {"id": 2, "stats": {"minutes": 90, "goals_scored": 0, "assists": 1, "bps": 20, "bonus": 0, "total_points": 6}, "explain": [{"fixture": 100}]},
            {"id": 3, "stats": {"minutes": 0, "goals_scored": 0, "assists": 0, "bps": 0, "bonus": 0, "total_points": 0}, "explain": []},
        ]
    }
    snap = build_live_snapshot(db_conn, live_payload=live_payload)
    by_player = {p["player_id"]: p for p in snap["points"]["by_player"]}

    assert by_player[1]["points"] == 12
    assert by_player[1]["multiplier"] == 2  # real captain multiplier
    assert by_player[2]["points"] == 6
    assert by_player[2]["multiplier"] == 1
    assert by_player[3]["points"] == 0
    assert by_player[3]["multiplier"] == 0  # a bench player scores nothing toward the squad, real fact
    assert by_player[3]["play_state"] == "yet_to_play"


def test_build_live_snapshot_logs_a_throttled_intragame_points_sample(db_conn, monkeypatch):
    """Real intragame (sub-GW) chart data (2026-08-28, direct user
    requirement: "do not fabricate history... store intragame snapshots
    for timestamp/overall points/squad points/captain points/rank...
    charts should become populated during the real GW, do not wait for
    the GW to finish"). Reuses the exact same append-only `decisions`
    journal pattern `live_charts.py::_intragame_rank_series` already
    proved out for rank - a new `live_points_sample` row per real
    `build_live_snapshot` call, throttled so a live match's fast poll
    cadence doesn't flood the journal."""
    import fpl_agent.monitoring.live_snapshot as ls_mod

    _seed_event(db_conn)
    _seed_player(db_conn, 1, web_name="Haaland")
    locked = _fake_locked_squad(2, starting_ids=[1], captain_id=1, source="locked_decision")
    monkeypatch.setattr(ls_mod, "get_locked_squad", lambda conn: locked)
    live_payload = {"elements": [{"id": 1, "stats": {"minutes": 90, "goals_scored": 1, "assists": 0, "bps": 30, "bonus": 0, "total_points": 8}, "explain": [{"fixture": 100}]}]}

    build_live_snapshot(db_conn, live_payload=live_payload)
    rows = db_conn.execute("SELECT detail FROM decisions WHERE decision_type='live_points_sample'").fetchall()
    assert len(rows) == 1
    detail = json.loads(rows[0]["detail"])
    assert detail["event"] == 2
    assert detail["points"] == 16.0  # real captain 2x multiplier over Haaland's 8 raw points
    assert detail["captain_points"] == 16.0

    # A second call immediately after must NOT log a second row - real
    # throttle, never one row per poll tick.
    build_live_snapshot(db_conn, live_payload=live_payload)
    rows_after = db_conn.execute("SELECT COUNT(*) c FROM decisions WHERE decision_type='live_points_sample'").fetchone()
    assert rows_after["c"] == 1


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
    assert cadence["rank"]["next_due_floor_minutes"] >= 1  # LiveFPL's own real minimum (lowered 5->1, 2026-09-12)


def test_decision_status_is_recomputing_while_a_real_auto_trigger_lock_is_fresh(db_conn):
    from datetime import datetime, timezone

    from fpl_agent.monitoring.live_snapshot import _decision_status

    now = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        "INSERT INTO app_meta (key, value, updated_at) VALUES ('strategic_plan_auto_started_at', ?, ?)",
        (now, now),
    )
    db_conn.commit()
    status, triggered_at = _decision_status(db_conn, is_stale=False)
    assert status == "RECOMPUTING"
    assert triggered_at == now  # real trigger timestamp, not a second guess


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
    assert _decision_status(db_conn, is_stale=False) == ("CURRENT", None)
    assert _decision_status(db_conn, is_stale=True) == ("STALE", None)


def test_decision_status_current_and_stale_without_any_lock(db_conn):
    from fpl_agent.monitoring.live_snapshot import _decision_status

    assert _decision_status(db_conn, is_stale=False) == ("CURRENT", None)
    assert _decision_status(db_conn, is_stale=True) == ("STALE", None)
    assert _decision_status(db_conn, is_stale=None) == ("UNKNOWN", None)


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
