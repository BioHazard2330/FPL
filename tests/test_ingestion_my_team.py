from fpl_agent.ingestion import my_team
from fpl_agent.ingestion.fpl_api import RawFetch
from fpl_agent.ingestion.my_team import get_latest_squad, get_my_team_entry_id, set_my_team_entry_id, sync_my_team


def _fake_raw(source_name, data):
    return RawFetch(source_name=source_name, data=data, retrieved_at="t0", latency_ms=1, parser_version="1")


def _fake_info():
    return {
        "player_first_name": "Pranav", "player_last_name": "Nair",
        "player_region_name": "Netherlands", "favourite_team": 16,
        "joined_time": "2026-08-20T22:22:30Z", "started_event": 1,
    }


def _fake_history(past=None, current=None):
    return {"past": past or [], "current": current or []}


def _fake_picks(active_chip=None):
    return {
        "active_chip": active_chip,
        "entry_history": {
            "event": 1, "points": 60, "total_points": 60, "overall_rank": 500000,
            "bank": 5, "value": 1000, "event_transfers": 0, "event_transfers_cost": 0,
            "points_on_bench": 8,
        },
        "picks": [
            {"element": 1, "position": 1, "multiplier": 1, "is_captain": False, "is_vice_captain": False},
            {"element": 2, "position": 2, "multiplier": 2, "is_captain": True, "is_vice_captain": False},
            {"element": 3, "position": 3, "multiplier": 1, "is_captain": False, "is_vice_captain": True},
        ],
    }


def _seed_event(conn, event_id, deadline_epoch):
    conn.execute(
        "INSERT INTO events (id,name,deadline_time,deadline_time_epoch,finished,is_previous,"
        "is_current,is_next,updated_at) VALUES (?,?,?,?,0,0,0,0,'t0')",
        (event_id, f"GW{event_id}", "t0", deadline_epoch),
    )
    conn.commit()


def test_set_and_get_my_team_entry_id_round_trips(db_conn):
    assert get_my_team_entry_id(db_conn) is None
    set_my_team_entry_id(db_conn, 7378572)
    assert get_my_team_entry_id(db_conn) == 7378572


def test_sync_my_team_saves_entry_and_season_history(db_conn, monkeypatch):
    monkeypatch.setattr(my_team.FPLApiAdapter, "fetch_entry_info", lambda self, entry_id: _fake_raw("x", _fake_info()))
    monkeypatch.setattr(
        my_team.FPLApiAdapter, "fetch_entry_history",
        lambda self, entry_id: _fake_raw("x", _fake_history(past=[
            {"season_name": "2024/25", "total_points": 1014, "rank": 10911576, "rank_percentage": "95"},
        ])),
    )

    result = sync_my_team(db_conn, 7378572)

    assert result["manager_name"] == "Pranav Nair"
    row = db_conn.execute("SELECT * FROM my_team_entry WHERE entry_id=7378572").fetchone()
    assert row["manager_name"] == "Pranav Nair"
    assert row["region_name"] == "Netherlands"
    hist = db_conn.execute("SELECT * FROM my_team_season_history WHERE entry_id=7378572").fetchone()
    assert hist["season_name"] == "2024/25"
    assert hist["rank"] == 10911576


def test_sync_my_team_skips_picks_when_no_event_has_locked(db_conn, monkeypatch):
    monkeypatch.setattr(my_team.FPLApiAdapter, "fetch_entry_info", lambda self, entry_id: _fake_raw("x", _fake_info()))
    monkeypatch.setattr(my_team.FPLApiAdapter, "fetch_entry_history", lambda self, entry_id: _fake_raw("x", _fake_history()))
    # An event exists but its deadline is in the far future - not locked yet.
    _seed_event(db_conn, 1, 9999999999)

    result = sync_my_team(db_conn, 7378572)

    assert result["picks"]["fetched"] is False
    assert "no gameweek has locked" in result["picks"]["reason"]
    assert get_latest_squad(db_conn, 7378572) is None


def test_sync_my_team_fetches_picks_for_the_latest_locked_event(db_conn, monkeypatch):
    monkeypatch.setattr(my_team.FPLApiAdapter, "fetch_entry_info", lambda self, entry_id: _fake_raw("x", _fake_info()))
    monkeypatch.setattr(my_team.FPLApiAdapter, "fetch_entry_history", lambda self, entry_id: _fake_raw("x", _fake_history()))
    monkeypatch.setattr(my_team.FPLApiAdapter, "fetch_entry_picks", lambda self, entry_id, event: _fake_raw("x", _fake_picks()))
    _seed_event(db_conn, 1, 0)  # deadline already passed (epoch 0)

    result = sync_my_team(db_conn, 7378572)

    assert result["picks"]["fetched"] is True
    assert result["picks"]["event"] == 1
    assert result["picks"]["picks_count"] == 3

    latest = get_latest_squad(db_conn, 7378572)
    assert latest == (1, [1, 2, 3])

    captain_row = db_conn.execute(
        "SELECT * FROM my_team_picks WHERE entry_id=7378572 AND player_id=2"
    ).fetchone()
    assert captain_row["is_captain"] == 1
    assert captain_row["multiplier"] == 2

    summary = db_conn.execute(
        "SELECT * FROM my_team_gw_summary WHERE entry_id=7378572 AND event=1"
    ).fetchone()
    assert summary["points"] == 60
    assert summary["overall_rank"] == 500000


def test_sync_my_team_picks_idempotent_without_force(db_conn, monkeypatch):
    monkeypatch.setattr(my_team.FPLApiAdapter, "fetch_entry_info", lambda self, entry_id: _fake_raw("x", _fake_info()))
    monkeypatch.setattr(my_team.FPLApiAdapter, "fetch_entry_history", lambda self, entry_id: _fake_raw("x", _fake_history()))
    calls = []

    def fake_fetch_picks(self, entry_id, event):
        calls.append(1)
        return _fake_raw("x", _fake_picks())

    monkeypatch.setattr(my_team.FPLApiAdapter, "fetch_entry_picks", fake_fetch_picks)
    _seed_event(db_conn, 1, 0)

    sync_my_team(db_conn, 7378572)
    sync_my_team(db_conn, 7378572)  # second call, no --force

    assert len(calls) == 1  # picks fetched only once - already-synced short-circuit


def test_sync_my_team_force_refetches_picks(db_conn, monkeypatch):
    monkeypatch.setattr(my_team.FPLApiAdapter, "fetch_entry_info", lambda self, entry_id: _fake_raw("x", _fake_info()))
    monkeypatch.setattr(my_team.FPLApiAdapter, "fetch_entry_history", lambda self, entry_id: _fake_raw("x", _fake_history()))
    calls = []

    def fake_fetch_picks(self, entry_id, event):
        calls.append(1)
        return _fake_raw("x", _fake_picks())

    monkeypatch.setattr(my_team.FPLApiAdapter, "fetch_entry_picks", fake_fetch_picks)
    _seed_event(db_conn, 1, 0)

    sync_my_team(db_conn, 7378572)
    sync_my_team(db_conn, 7378572, force=True)

    assert len(calls) == 2


def test_sync_my_team_records_active_chip(db_conn, monkeypatch):
    monkeypatch.setattr(my_team.FPLApiAdapter, "fetch_entry_info", lambda self, entry_id: _fake_raw("x", _fake_info()))
    monkeypatch.setattr(my_team.FPLApiAdapter, "fetch_entry_history", lambda self, entry_id: _fake_raw("x", _fake_history()))
    monkeypatch.setattr(
        my_team.FPLApiAdapter, "fetch_entry_picks",
        lambda self, entry_id, event: _fake_raw("x", _fake_picks(active_chip="wildcard")),
    )
    _seed_event(db_conn, 1, 0)

    sync_my_team(db_conn, 7378572)

    row = db_conn.execute("SELECT active_chip FROM my_team_picks WHERE entry_id=7378572 LIMIT 1").fetchone()
    assert row["active_chip"] == "wildcard"
